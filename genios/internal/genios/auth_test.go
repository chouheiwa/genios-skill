package genios

import (
	"os"
	"path/filepath"
	"testing"
)

func TestEncryptPassword(t *testing.T) {
	got := EncryptPassword("Sample#Pass123")
	want := "6ece634a06a0f30ef606e557f0237718"
	if got != want {
		t.Fatalf("got %s want %s", got, want)
	}
}

func TestWorkspaceFromProjectConfig(t *testing.T) {
	dir := t.TempDir()
	config := "| 团队空间 WorkspaceID | `ws-from-project` | 所有资源都放这里 |\n"
	if err := os.WriteFile(filepath.Join(dir, "genios-project.md"), []byte(config), 0600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("GENIOS_PROJECT_ROOT", dir)
	t.Setenv("GENIOS_TEAM_WORKSPACE", "")
	if got := Workspace(); got != "ws-from-project" {
		t.Fatalf("got %q want %q", got, "ws-from-project")
	}
}

func TestWorkspaceEnvironmentOverridesProjectConfig(t *testing.T) {
	dir := t.TempDir()
	config := "| 团队空间 WorkspaceID | `ws-from-project` | |\n"
	if err := os.WriteFile(filepath.Join(dir, "genios-project.md"), []byte(config), 0600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("GENIOS_PROJECT_ROOT", dir)
	t.Setenv("GENIOS_TEAM_WORKSPACE", "ws-from-env")
	if got := Workspace(); got != "ws-from-env" {
		t.Fatalf("got %q want %q", got, "ws-from-env")
	}
}
