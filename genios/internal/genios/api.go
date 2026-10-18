package genios

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

var Versions = map[string]string{"app": "2023-08-01", "aigw": "2023-08-01", "iam": "2024-12-25", "observe": "2025-05-01"}

type Client struct {
	Base      string
	Session   Session
	Workspace string
	HTTP      *http.Client
}

func NewClient(s Session, ws string) *Client {
	return &Client{Base: getenv("GENIOS_BASE_URL_MANAGE", "https://coze.nankai.edu.cn/api"), Session: s, Workspace: ws, HTTP: &http.Client{Timeout: 30 * time.Second}}
}
func getenv(k, d string) string {
	if v := strings.TrimSpace(os.Getenv(k)); v != "" {
		return v
	}
	return d
}

func (c *Client) Call(action string, body map[string]any, svc string) (map[string]any, error) {
	if c.Workspace == "" {
		return nil, fmt.Errorf("缺少团队空间 ID；请设置 GENIOS_TEAM_WORKSPACE")
	}
	if svc == "" {
		svc = "app"
	}
	b := map[string]any{}
	for k, v := range body {
		b[k] = v
	}
	b["WorkspaceID"] = c.Workspace
	raw, _ := json.Marshal(b)
	ver := Versions[svc]
	if ver == "" {
		ver = "2023-08-01"
	}
	u := fmt.Sprintf("%s/%s?Action=%s&Version=%s&X-Account-Id=%s", strings.TrimRight(c.Base, "/"), svc, url.QueryEscape(action), url.QueryEscape(ver), AccountID)
	req, _ := http.NewRequest("POST", u, bytes.NewReader(raw))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("accept", "application/json")
	req.Header.Set("x-csrf-token", c.Session.CSRF)
	req.Header.Set("x-top-region", "cn-north-1")
	req.Header.Set("WorkspaceID", c.Workspace)
	req.Header.Set("Cookie", c.Session.Cookie)
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	text, _ := io.ReadAll(io.LimitReader(resp.Body, 2<<20))
	if resp.StatusCode == 301 || resp.StatusCode == 302 || resp.StatusCode == 303 || resp.StatusCode == 401 {
		return nil, fmt.Errorf("会话失效（HTTP %d）", resp.StatusCode)
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("%s: HTTP %d: %s", action, resp.StatusCode, string(text))
	}
	var data map[string]any
	if err = json.Unmarshal(text, &data); err != nil {
		return nil, fmt.Errorf("%s: 返回非 JSON", action)
	}
	if meta, ok := data["ResponseMetadata"].(map[string]any); ok {
		if e, exists := meta["Error"]; exists && e != nil {
			return nil, fmt.Errorf("%s: 业务错误 %v", action, e)
		}
	}
	if result, ok := data["Result"].(map[string]any); ok {
		return result, nil
	}
	return map[string]any{}, nil
}
