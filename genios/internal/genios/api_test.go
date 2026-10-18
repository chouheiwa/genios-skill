package genios

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestCallForcesWorkspaceAndUsesService(t *testing.T) {
	var got map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewDecoder(r.Body).Decode(&got)
		if r.URL.Path != "/observe" {
			t.Fatalf("path %s", r.URL.Path)
		}
		w.Header().Set("content-type", "application/json")
		w.Write([]byte(`{"Result":{"ok":true}}`))
	}))
	defer srv.Close()
	c := NewClient(Session{Cookie: "c", CSRF: "x"}, "team")
	c.Base = srv.URL
	out, e := c.Call("ListTraceSpans", map[string]any{"WorkspaceID": "wrong"}, "observe")
	if e != nil {
		t.Fatal(e)
	}
	if got["WorkspaceID"] != "team" {
		t.Fatalf("workspace was %v", got["WorkspaceID"])
	}
	if out["ok"] != true {
		t.Fatal(out)
	}
}
