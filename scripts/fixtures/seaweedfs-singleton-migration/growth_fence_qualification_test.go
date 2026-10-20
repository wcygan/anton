package weed_server

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestQualificationHTTPGrowthFence(t *testing.T) {
	for _, method := range []string{http.MethodGet, http.MethodPost} {
		for _, disabled := range []bool{true, false} {
			topo, _ := changedTestCluster(t)
			ms := &MasterServer{Topo: topo, option: &MasterOption{VolumeGrowthDisabled: disabled, DefaultReplicaPlacement: "001"}}
			req := httptest.NewRequest(method, "/vol/grow?count=999999&replication=001", nil)
			out := httptest.NewRecorder()
			ms.volumeGrowHandler(out, req)
			expected := http.StatusNotAcceptable
			if disabled {
				expected = http.StatusServiceUnavailable
			}
			if out.Code != expected {
				t.Fatalf("method=%s disabled=%v status=%d want=%d body=%s", method, disabled, out.Code, expected, out.Body.String())
			}
			if disabled && !strings.Contains(out.Body.String(), "volume growth disabled") {
				t.Fatalf("unexpected denial: %s", out.Body.String())
			}
		}
	}
}
