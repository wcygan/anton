package v1

import "testing"

func TestQualificationComponentDigestOverrides(t *testing.T) {
	const baseline = "4.40@sha256:5b28dd52da45622d0a1c3a6d65281eb171be3ff7cac40e1a328c074882f7370c"
	const candidate = "4.48@sha256:aba492e2a4e4c90bff795745e8e660affa1f09e7650f5981bd7bccd1a06cd931"
	for _, version := range []string{baseline, candidate} {
		actual := applyVersion("chrislusf/seaweedfs:4.40", version)
		if actual != "chrislusf/seaweedfs:"+version {
			t.Fatalf("component override %q rendered %q", version, actual)
		}
	}
	// A digest on the shared image takes precedence over every version field.
	// Therefore stage with component overrides before normalizing the shared pin.
	pinned := "chrislusf/seaweedfs:" + candidate
	if actual := applyVersion(pinned, baseline); actual != pinned {
		t.Fatalf("shared digest precedence changed: %q", actual)
	}
}
