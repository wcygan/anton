package controller

import (
	"context"
	"strings"
	"testing"

	"github.com/go-logr/logr"
	seaweedv1 "github.com/seaweedfs/seaweedfs-operator/api/v1"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/tools/record"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
)

func TestQualificationExistingPVCExpansionNeedsManualProcedure(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = appsv1.AddToScheme(scheme)
	_ = corev1.AddToScheme(scheme)
	pvc := corev1.PersistentVolumeClaim{ObjectMeta: metav1.ObjectMeta{Name: "existing", Namespace: "lab", UID: types.UID("original-pvc")}, Spec: corev1.PersistentVolumeClaimSpec{Resources: corev1.VolumeResourceRequirements{Requests: corev1.ResourceList{corev1.ResourceStorage: resource.MustParse("120Gi")}}}}
	existing := &appsv1.StatefulSet{ObjectMeta: metav1.ObjectMeta{Name: "sw-volume", Namespace: "lab", UID: types.UID("original-sts")}, Spec: appsv1.StatefulSetSpec{VolumeClaimTemplates: []corev1.PersistentVolumeClaim{pvc}}}
	desired := existing.DeepCopy()
	desired.Spec.VolumeClaimTemplates[0].Spec.Resources.Requests[corev1.ResourceStorage] = resource.MustParse("160Gi")
	cli := fake.NewClientBuilder().WithScheme(scheme).WithObjects(existing, &pvc).Build()
	recorder := record.NewFakeRecorder(4)
	reconciler := &SeaweedReconciler{Client: cli, Log: logr.Discard(), Scheme: scheme, Recorder: recorder}
	if err := reconciler.reconcileVolumeClaimTemplates(context.Background(), &seaweedv1.Seaweed{}, existing, desired); err != nil {
		t.Fatal(err)
	}
	gotPVC := &corev1.PersistentVolumeClaim{}
	gotSTS := &appsv1.StatefulSet{}
	if err := cli.Get(context.Background(), types.NamespacedName{Name: "existing", Namespace: "lab"}, gotPVC); err != nil {
		t.Fatal(err)
	}
	if err := cli.Get(context.Background(), types.NamespacedName{Name: "sw-volume", Namespace: "lab"}, gotSTS); err != nil {
		t.Fatal(err)
	}
	for label, claim := range map[string]corev1.PersistentVolumeClaim{"pvc": *gotPVC, "template": gotSTS.Spec.VolumeClaimTemplates[0]} {
		actual := claim.Spec.Resources.Requests[corev1.ResourceStorage]
		if actual.Cmp(resource.MustParse("120Gi")) != 0 {
			t.Fatalf("%s unexpectedly resized to %s", label, actual.String())
		}
	}
	if gotPVC.UID != "original-pvc" || gotSTS.UID != "original-sts" {
		t.Fatal("original identities lost")
	}
	select {
	case event := <-recorder.Events:
		if !strings.Contains(event, "Warning VolumeClaimTemplatesMismatch") {
			t.Fatalf("wrong event: %s", event)
		}
	default:
		t.Fatal("missing storage-template drift warning")
	}
}
