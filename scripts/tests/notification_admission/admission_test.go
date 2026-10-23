package notificationadmission

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/google/cel-go/cel"
	"github.com/google/cel-go/common/types"
	admissionv1 "k8s.io/api/admission/v1"
	registrationv1 "k8s.io/api/admissionregistration/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/util/version"
	"k8s.io/apiserver/pkg/admission"
	admissioncel "k8s.io/apiserver/pkg/admission/plugin/cel"
	celconfig "k8s.io/apiserver/pkg/apis/cel"
	apiservercel "k8s.io/apiserver/pkg/cel"
	"k8s.io/apiserver/pkg/cel/environment"
	"sigs.k8s.io/yaml"
)

const identity = "system:serviceaccount:flux-system:notification-controller-restricted"
const annotation = "reconcile.fluxcd.io/requestedAt"
const newRequest = "2026-10-19 03:30:00 +0000 UTC m=+100.000000001"

var app = filepath.Join("..", "..", "..", "kubernetes", "apps", "flux-system", "flux-instance", "app")

type expression struct {
	name, text string
	boolean    bool
}

func (e expression) GetExpression() string { return e.text }
func (e expression) GetName() string       { return e.name }
func (e expression) ReturnTypes() []*cel.Type {
	if e.boolean {
		return []*cel.Type{cel.BoolType}
	}
	return []*cel.Type{cel.AnyType}
}

func loadPolicy(t *testing.T) (*registrationv1.ValidatingAdmissionPolicy, *registrationv1.ValidatingAdmissionPolicyBinding) {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(app, "notification-admission.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	var policy registrationv1.ValidatingAdmissionPolicy
	var binding registrationv1.ValidatingAdmissionPolicyBinding
	count := 0
	for _, document := range strings.Split(string(data), "\n---\n") {
		var header struct {
			Kind string `json:"kind"`
		}
		if err := yaml.Unmarshal([]byte(document), &header); err != nil {
			t.Fatal(err)
		}
		switch header.Kind {
		case "ValidatingAdmissionPolicy":
			err = yaml.UnmarshalStrict([]byte(document), &policy)
		case "ValidatingAdmissionPolicyBinding":
			err = yaml.UnmarshalStrict([]byte(document), &binding)
		default:
			t.Fatalf("unexpected kind %q", header.Kind)
		}
		if err != nil {
			t.Fatal(err)
		}
		count++
	}
	if count != 2 {
		t.Fatalf("expected policy and binding, got %d objects", count)
	}
	return &policy, &binding
}

type evaluator struct {
	compiler             *admissioncel.CompositedCompiler
	matches, validations admissioncel.ConditionEvaluator
	policy               *registrationv1.ValidatingAdmissionPolicy
}

func newEvaluator(t *testing.T) *evaluator {
	t.Helper()
	policy, _ := loadPolicy(t)
	compiler, err := admissioncel.NewCompositedCompiler(environment.MustBaseEnvSet(version.MajorMinor(1, 36)))
	if err != nil {
		t.Fatal(err)
	}
	options := admissioncel.OptionalVariableDeclarations{}
	for _, v := range policy.Spec.Variables {
		result := compiler.CompileAndStoreVariable(expression{name: v.Name, text: v.Expression}, options, environment.NewExpressions)
		if result.Error != nil {
			t.Fatalf("variable %s: %v", v.Name, result.Error)
		}
	}
	matches := []admissioncel.ExpressionAccessor{}
	for _, m := range policy.Spec.MatchConditions {
		matches = append(matches, expression{text: m.Expression, boolean: true})
	}
	validations := []admissioncel.ExpressionAccessor{}
	for _, v := range policy.Spec.Validations {
		validations = append(validations, expression{text: v.Expression, boolean: true})
	}
	matchEvaluator := compiler.CompileCondition(matches, options, environment.NewExpressions)
	validationEvaluator := compiler.CompileCondition(validations, options, environment.NewExpressions)
	for _, e := range []admissioncel.ConditionEvaluator{matchEvaluator, validationEvaluator} {
		if errs := e.CompilationErrors(); len(errs) > 0 {
			t.Fatal(errs)
		}
	}
	return &evaluator{compiler: compiler, matches: matchEvaluator, validations: validationEvaluator, policy: policy}
}

// Resource matching is tested separately; these inputs use the rule's canonical v1.
func (e *evaluator) evaluate(t *testing.T, old, next map[string]interface{}, user, namespace, subresource string) string {
	t.Helper()
	group := strings.Split(next["apiVersion"].(string), "/")[0]
	resource := "gitrepositories"
	kind := "GitRepository"
	if group == "kustomize.toolkit.fluxcd.io" {
		resource = "kustomizations"
		kind = "Kustomization"
	}
	request := &admissionv1.AdmissionRequest{Namespace: namespace, Name: "flux-system", Operation: admissionv1.Update, SubResource: subresource, Resource: metav1.GroupVersionResource{Group: group, Version: "v1", Resource: resource}}
	request.UserInfo.Username = user
	attrs := &admission.VersionedAttributes{VersionedObject: &unstructured.Unstructured{Object: next}, VersionedOldObject: &unstructured.Unstructured{Object: old}, VersionedKind: schema.GroupVersionKind{Group: group, Version: "v1", Kind: kind}}
	ctx := e.compiler.CreateContext(context.Background())
	results, _, err := e.matches.ForInput(ctx, attrs, request, admissioncel.OptionalVariableBindings{}, nil, celconfig.RuntimeCELCostBudget)
	if err != nil {
		return "deny"
	}
	anyFalse := false
	for _, r := range results {
		if r.Error == nil && r.EvalResult == types.False {
			anyFalse = true
		}
	}
	if anyFalse {
		return "skip"
	}
	for _, r := range results {
		if r.Error != nil || r.EvalResult != types.True {
			return "deny"
		}
	}
	results, _, err = e.validations.ForInput(ctx, attrs, request, admissioncel.OptionalVariableBindings{}, nil, celconfig.RuntimeCELCostBudget)
	if err != nil {
		t.Logf("validation evaluation error: %v", err)
		return "error"
	}
	for _, r := range results {
		if r.Error != nil {
			t.Logf("evaluation error: %v", r.Error)
			return "error"
		}
		if r.EvalResult != types.True {
			t.Logf("validation rejected: %s: %v / %v", r.ExpressionAccessor.GetExpression(), r.EvalResult, r.Error)
			return "deny"
		}
	}
	return "allow"
}

func object(kind string) map[string]interface{} {
	group := "source.toolkit.fluxcd.io"
	spec := map[string]interface{}{"url": "https://github.com/wcygan/anton.git", "ref": map[string]interface{}{"branch": "main"}}
	if kind == "Kustomization" {
		group = "kustomize.toolkit.fluxcd.io"
		spec = map[string]interface{}{"path": "./kubernetes/flux/cluster", "prune": true, "sourceRef": map[string]interface{}{"kind": "GitRepository", "name": "flux-system"}}
	}
	return map[string]interface{}{"apiVersion": group + "/v1", "kind": kind, "metadata": map[string]interface{}{"name": "flux-system", "namespace": "flux-system", "uid": "existing-uid", "resourceVersion": "123", "generation": int64(1), "labels": map[string]interface{}{"owner": "flux"}, "annotations": map[string]interface{}{annotation: "previous", "kustomize.toolkit.fluxcd.io/reconcile": "enabled"}, "finalizers": []interface{}{"finalizers.fluxcd.io"}, "ownerReferences": []interface{}{map[string]interface{}{"apiVersion": "v1", "kind": "ConfigMap", "name": "owner", "uid": "owner-uid"}}}, "spec": spec, "status": map[string]interface{}{"observedGeneration": int64(1)}}
}
func clone(in map[string]interface{}) map[string]interface{} {
	return (&unstructured.Unstructured{Object: in}).DeepCopy().Object
}
func metadata(in map[string]interface{}) map[string]interface{} {
	return in["metadata"].(map[string]interface{})
}
func annotations(in map[string]interface{}) map[string]interface{} {
	return metadata(in)["annotations"].(map[string]interface{})
}
func requestOnly(in map[string]interface{}) { annotations(in)[annotation] = newRequest }

func TestNotificationAdmissionBoundary(t *testing.T) {
	e := newEvaluator(t)
	tests := []struct {
		name   string
		change func(map[string]interface{})
		want   string
	}{
		{"request reconciliation", requestOnly, "allow"},
		{"no-op preserves existing request", func(x map[string]interface{}) {}, "allow"},
		{"server bookkeeping", func(x map[string]interface{}) {
			requestOnly(x)
			metadata(x)["resourceVersion"] = "124"
			metadata(x)["managedFields"] = []interface{}{map[string]interface{}{"manager": "notification-controller", "operation": "Update"}}
		}, "allow"},
		{"change spec", func(x map[string]interface{}) { x["spec"].(map[string]interface{})["suspend"] = true }, "deny"},
		{"bundle spec with valid request", func(x map[string]interface{}) { requestOnly(x); x["spec"].(map[string]interface{})["suspend"] = true }, "deny"},
		{"delete spec", func(x map[string]interface{}) { requestOnly(x); delete(x, "spec") }, "deny"},
		{"add top-level field", func(x map[string]interface{}) { requestOnly(x); x["futureField"] = "payload" }, "deny"},
		{"change status", func(x map[string]interface{}) {
			requestOnly(x)
			x["status"].(map[string]interface{})["observedGeneration"] = int64(99)
		}, "deny"},
		{"remove status", func(x map[string]interface{}) { requestOnly(x); delete(x, "status") }, "deny"},
		{"change labels", func(x map[string]interface{}) {
			requestOnly(x)
			metadata(x)["labels"].(map[string]interface{})["owner"] = "attacker"
		}, "deny"},
		{"remove labels", func(x map[string]interface{}) { requestOnly(x); delete(metadata(x), "labels") }, "deny"},
		{"remove finalizers", func(x map[string]interface{}) { requestOnly(x); metadata(x)["finalizers"] = []interface{}{} }, "deny"},
		{"change owners", func(x map[string]interface{}) { requestOnly(x); metadata(x)["ownerReferences"] = []interface{}{} }, "deny"},
		{"add other annotation", func(x map[string]interface{}) {
			requestOnly(x)
			annotations(x)["reconcile.fluxcd.io/forceAt"] = "force"
		}, "deny"},
		{"change other annotation", func(x map[string]interface{}) {
			requestOnly(x)
			annotations(x)["kustomize.toolkit.fluxcd.io/reconcile"] = "disabled"
		}, "deny"},
		{"remove other annotation", func(x map[string]interface{}) {
			requestOnly(x)
			delete(annotations(x), "kustomize.toolkit.fluxcd.io/reconcile")
		}, "deny"},
		{"remove reconcile annotation", func(x map[string]interface{}) { delete(annotations(x), annotation) }, "deny"},
		{"empty request", func(x map[string]interface{}) { annotations(x)[annotation] = "" }, "deny"},
		{"oversized request", func(x map[string]interface{}) { annotations(x)[annotation] = strings.Repeat("x", 129) }, "deny"},
		{"non-string request", func(x map[string]interface{}) { annotations(x)[annotation] = int64(1) }, "error"},
		{"change identity", func(x map[string]interface{}) { requestOnly(x); metadata(x)["uid"] = "different" }, "deny"},
		{"add protected metadata", func(x map[string]interface{}) { requestOnly(x); metadata(x)["generateName"] = "attacker-" }, "deny"},
	}
	for _, kind := range []string{"GitRepository", "Kustomization"} {
		for _, tc := range tests {
			t.Run(kind+"/"+tc.name, func(t *testing.T) {
				old := object(kind)
				next := clone(old)
				tc.change(next)
				if got := e.evaluate(t, old, next, identity, "flux-system", ""); got != tc.want {
					t.Fatalf("got %s, want %s", got, tc.want)
				}
			})
		}
		t.Run(kind+"/missing annotations", func(t *testing.T) {
			old := object(kind)
			delete(metadata(old), "annotations")
			next := clone(old)
			metadata(next)["annotations"] = map[string]interface{}{annotation: newRequest}
			if got := e.evaluate(t, old, next, identity, "flux-system", ""); got != "allow" {
				t.Fatal(got)
			}
		})
		t.Run(kind+"/null old annotations", func(t *testing.T) {
			old := object(kind)
			metadata(old)["annotations"] = nil
			next := clone(old)
			metadata(next)["annotations"] = map[string]interface{}{annotation: newRequest}
			if got := e.evaluate(t, old, next, identity, "flux-system", ""); got != "allow" {
				t.Fatal(got)
			}
		})
		t.Run(kind+"/status subresource", func(t *testing.T) {
			old := object(kind)
			next := clone(old)
			requestOnly(next)
			if got := e.evaluate(t, old, next, identity, "flux-system", "status"); got != "deny" {
				t.Fatal(got)
			}
		})
		t.Run(kind+"/nested configuration change", func(t *testing.T) {
			old := object(kind)
			next := clone(old)
			requestOnly(next)
			if kind == "GitRepository" {
				next["spec"].(map[string]interface{})["ref"].(map[string]interface{})["branch"] = "attacker"
			} else {
				next["spec"].(map[string]interface{})["sourceRef"].(map[string]interface{})["name"] = "auxiliary"
			}
			if got := e.evaluate(t, old, next, identity, "flux-system", ""); got != "deny" {
				t.Fatal(got)
			}
		})
		for _, user := range []string{"system:serviceaccount:flux-system:source-controller", "system:serviceaccount:flux-system:kustomize-controller", "system:serviceaccount:flux-system:flux-operator", "system:serviceaccount:flux-system:helm-controller", "system:serviceaccount:flux-system:image-automation-controller", "system:serviceaccount:flux-system:image-reflector-controller", "system:serviceaccount:flux-system:notification-controller", identity + "-other", "operator-admin"} {
			t.Run(kind+"/unaffected "+user, func(t *testing.T) {
				old := object(kind)
				next := clone(old)
				next["spec"].(map[string]interface{})["suspend"] = true
				if got := e.evaluate(t, old, next, user, "flux-system", ""); got != "skip" {
					t.Fatal(got)
				}
			})
		}
		t.Run(kind+"/other namespace", func(t *testing.T) {
			old := object(kind)
			next := clone(old)
			next["spec"].(map[string]interface{})["suspend"] = true
			if got := e.evaluate(t, old, next, identity, "other", ""); got != "skip" {
				t.Fatal(got)
			}
		})
	}
}

func TestPolicyScopeAndBinding(t *testing.T) {
	p, b := loadPolicy(t)
	if p.APIVersion != "admissionregistration.k8s.io/v1" || p.Name != "notification-controller-reconcile-only" || p.Spec.FailurePolicy == nil || *p.Spec.FailurePolicy != registrationv1.Fail {
		t.Fatal("policy must be v1 and fail closed")
	}
	if p.Spec.MatchConstraints.MatchPolicy == nil || *p.Spec.MatchConstraints.MatchPolicy != registrationv1.Equivalent {
		t.Fatal("equivalent API versions must match")
	}
	if p.Spec.MatchConstraints.NamespaceSelector != nil || p.Spec.MatchConstraints.ObjectSelector != nil || len(p.Spec.MatchConstraints.ExcludeResourceRules) != 0 || p.Spec.ParamKind != nil || b.Spec.MatchResources != nil || b.Spec.ParamRef != nil {
		t.Fatal("selectors, exclusions, and parameters must not narrow or bypass this guard")
	}
	rules := p.Spec.MatchConstraints.ResourceRules
	if len(rules) != 2 {
		t.Fatal("expected exactly two rules")
	}
	for i, group := range []string{"source.toolkit.fluxcd.io", "kustomize.toolkit.fluxcd.io"} {
		resource := []string{"gitrepositories", "kustomizations"}[i]
		r := rules[i]
		if !reflect.DeepEqual(r.APIGroups, []string{group}) || !reflect.DeepEqual(r.APIVersions, []string{"v1"}) || !reflect.DeepEqual(r.ResourceNames, []string{"flux-system"}) || !reflect.DeepEqual(r.Operations, []registrationv1.OperationType{registrationv1.Update}) || !reflect.DeepEqual(r.Resources, []string{resource, resource + "/status"}) || r.Scope == nil || *r.Scope != registrationv1.NamespacedScope {
			t.Fatalf("unexpected resource rule: %#v", r)
		}
	}
	if len(p.Spec.MatchConditions) != 2 || len(p.Spec.Validations) != 5 || len(p.Spec.Variables) != 2 {
		t.Fatal("unexpected policy shape")
	}
	for _, validation := range p.Spec.Validations {
		if validation.Reason == nil || *validation.Reason != metav1.StatusReasonForbidden {
			t.Fatal("guard denials must be Forbidden, distinguishable from malformed requests")
		}
	}
	if b.Spec.PolicyName != p.Name || !reflect.DeepEqual(b.Spec.ValidationActions, []registrationv1.ValidationAction{registrationv1.Deny}) {
		t.Fatal("binding must deny violations of this exact policy")
	}
	data, err := os.ReadFile(filepath.Join(app, "kustomization.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	var k struct {
		Resources []string `json:"resources"`
	}
	if err := yaml.Unmarshal(data, &k); err != nil {
		t.Fatal(err)
	}
	found := false
	for _, r := range k.Resources {
		if r == "./notification-admission.yaml" {
			found = true
		}
	}
	if !found {
		t.Fatal("policy is not wired into the owning app")
	}
}

func TestCapturedTargetShapes(t *testing.T) {
	path := os.Getenv("NOTIFICATION_ADMISSION_FIXTURES")
	if path == "" {
		t.Skip("optional current target snapshots not supplied")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var objects []map[string]interface{}
	if err := json.Unmarshal(data, &objects); err != nil {
		t.Fatal(err)
	}
	if len(objects) != 2 {
		t.Fatal("expected both target snapshots")
	}
	e := newEvaluator(t)
	for _, old := range objects {
		t.Run(old["kind"].(string), func(t *testing.T) {
			next := clone(old)
			requestOnly(next)
			if got := e.evaluate(t, old, next, identity, "flux-system", ""); got != "allow" {
				t.Fatalf("current shape rejected: %s", got)
			}
			next["spec"].(map[string]interface{})["suspend"] = true
			if got := e.evaluate(t, old, next, identity, "flux-system", ""); got != "deny" {
				t.Fatalf("configuration mutation accepted: %s", got)
			}
		})
	}
}

// Typed objects are not iterable maps during API-server schema checking.
// The runtime evaluator uses dynamic objects, so test both compilation paths.
func TestSchemaTypedObjectComparisons(t *testing.T) {
	policy, _ := loadPolicy(t)
	for _, kind := range []string{"GitRepository", "Kustomization"} {
		t.Run(kind, func(t *testing.T) {
			metadata := apiservercel.NewObjectType(kind+"Metadata", map[string]*apiservercel.DeclField{
				"annotations": apiservercel.NewDeclField("annotations", apiservercel.NewMapType(apiservercel.StringType, apiservercel.StringType, -1), false, nil, nil),
			})
			object := apiservercel.NewObjectType(kind, map[string]*apiservercel.DeclField{
				"metadata": apiservercel.NewDeclField("metadata", metadata, true, nil, nil),
			})
			envSet, err := environment.MustBaseEnvSet(version.MajorMinor(1, 36)).Extend(environment.VersionedOptions{
				IntroducedVersion: version.MajorMinor(1, 0),
				DeclTypes:         []*apiservercel.DeclType{object},
				EnvOptions:        []cel.EnvOption{cel.Variable("object", object.CelType()), cel.Variable("oldObject", object.CelType()), cel.Variable("request", cel.DynType), cel.Variable("variables", cel.DynType)},
			})
			if err != nil {
				t.Fatal(err)
			}
			env, err := envSet.Env(environment.NewExpressions)
			if err != nil {
				t.Fatal(err)
			}
			for _, v := range policy.Spec.Validations {
				if _, issues := env.Compile(v.Expression); issues.Err() != nil {
					t.Fatal(issues.Err())
				}
			}
			for _, bad := range []string{"object.all(k, true)", "object.metadata.all(k, true)"} {
				if _, issues := env.Compile(bad); issues.Err() == nil {
					t.Fatalf("regression check did not reject typed map iteration: %s", bad)
				}
			}
		})
	}
}
