package genios

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/md5"
	"crypto/sha1"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

const (
	Platform  = "https://coze.nankai.edu.cn"
	IAM       = "https://iam.nankai.edu.cn"
	AccountID = "1000000000"
)

type Credentials struct{ Account, Password string }
type Session struct{ Cookie, CSRF string }

func ProjectRoot() string {
	if v := os.Getenv("GENIOS_PROJECT_ROOT"); v != "" {
		return v
	}
	wd, _ := os.Getwd()
	return wd
}
func CredentialsPath() string {
	if v := os.Getenv("GENIOS_CREDENTIALS_FILE"); v != "" {
		return v
	}
	if dir, err := os.UserConfigDir(); err == nil {
		return filepath.Join(dir, "genios", "credentials.env")
	}
	return filepath.Join(ProjectRoot(), "genios-credentials.env")
}
func SessionPath() string {
	if v := os.Getenv("GENIOS_SESSION_FILE"); v != "" {
		return v
	}
	if dir, err := os.UserConfigDir(); err == nil {
		return filepath.Join(dir, "genios", "session.env")
	}
	return filepath.Join(os.TempDir(), "genios-session.env")
}
func Workspace() string {
	if v := strings.TrimSpace(os.Getenv("GENIOS_TEAM_WORKSPACE")); v != "" {
		return v
	}
	path := filepath.Join(ProjectRoot(), "genios-project.md")
	b, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(string(b), "\n") {
		cells := strings.Split(line, "|")
		if len(cells) < 3 || !strings.Contains(cells[1], "WorkspaceID") {
			continue
		}
		value := strings.Trim(strings.TrimSpace(cells[2]), "`")
		if value != "" && !strings.HasPrefix(value, "<") {
			return value
		}
	}
	return ""
}
func OutsideProject(path string) error {
	root, _ := filepath.Abs(ProjectRoot())
	p, _ := filepath.Abs(path)
	if p == root || strings.HasPrefix(p, root+string(os.PathSeparator)) {
		return fmt.Errorf("会话文件不能放在项目目录内，请把 GENIOS_SESSION_FILE 指到项目外")
	}
	return nil
}
func ReadCredentials(path string) (Credentials, error) {
	root := ProjectRoot()
	abs, _ := filepath.Abs(path)
	rootAbs, _ := filepath.Abs(root)
	if abs == rootAbs || strings.HasPrefix(abs, rootAbs+string(os.PathSeparator)) {
		cmd := exec.Command("git", "-C", rootAbs, "check-ignore", "-q", abs)
		if err := cmd.Run(); err != nil {
			return Credentials{}, fmt.Errorf("%s 在项目目录内但没有被 git 忽略，请先加入 .gitignore", path)
		}
	}
	st, err := os.Stat(path)
	if err != nil {
		return Credentials{}, err
	}
	if st.Mode().Perm()&0077 != 0 {
		return Credentials{}, fmt.Errorf("%s 权限过宽，请执行 chmod 600", path)
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return Credentials{}, err
	}
	var c Credentials
	for _, line := range strings.Split(string(b), "\n") {
		k, v, ok := strings.Cut(strings.TrimSpace(line), "=")
		if !ok {
			continue
		}
		switch strings.TrimSpace(k) {
		case "ACCOUNT":
			c.Account = strings.TrimSpace(v)
		case "PASSWORD":
			c.Password = strings.TrimSpace(v)
		}
	}
	if c.Account == "" || c.Password == "" {
		return c, errors.New("凭据文件缺少 ACCOUNT 或 PASSWORD")
	}
	return c, nil
}
func LoadSession(path string) (Session, error) {
	if path == "" {
		return Session{}, errors.New("缺少 GENIOS_SESSION_FILE")
	}
	if err := OutsideProject(path); err != nil {
		return Session{}, err
	}
	if st, err := os.Stat(path); err == nil && st.Mode().Perm()&0077 != 0 {
		return Session{}, fmt.Errorf("%s 权限过宽，请执行 chmod 600", path)
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return Session{}, err
	}
	var s Session
	for _, line := range strings.Split(string(b), "\n") {
		k, v, ok := strings.Cut(strings.TrimSpace(line), "=")
		if !ok {
			continue
		}
		v = strings.Trim(v, "'\"")
		if k == "COOKIE" {
			s.Cookie = v
		}
		if k == "CSRF" {
			s.CSRF = v
		}
	}
	if s.Cookie == "" || s.CSRF == "" {
		return s, errors.New("会话文件缺少 COOKIE 或 CSRF")
	}
	return s, nil
}
func WriteSession(s Session, path string) error {
	if err := OutsideProject(path); err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0600)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = fmt.Fprintf(f, "COOKIE=%s\nCSRF=%s\n", s.Cookie, s.CSRF)
	return err
}
func EncryptPassword(password string) string {
	h := md5.Sum([]byte("9007199254740991"))
	key := hex.EncodeToString(h[:])
	sh := sha1.Sum([]byte(key))
	iv := []byte(hex.EncodeToString(sh[:])[:16])
	block, _ := aes.NewCipher([]byte(key))
	p := []byte(strings.TrimSpace(password))
	n := aes.BlockSize - len(p)%aes.BlockSize
	for i := 0; i < n; i++ {
		p = append(p, byte(n))
	}
	out := make([]byte, len(p))
	cipher.NewCBCEncrypter(block, iv).CryptBlocks(out, p)
	return hex.EncodeToString(out)
}

func Login(account, password string) (Session, error) {
	jar, _ := cookiejar.New(nil)
	c := &http.Client{Jar: jar, Timeout: 30 * time.Second}
	page, err := c.Get(Platform + "/")
	if err != nil {
		return Session{}, err
	}
	defer page.Body.Close()
	if page.Request.URL.Hostname() != "iam.nankai.edu.cn" || !strings.HasPrefix(page.Request.URL.Path, "/login") {
		return Session{}, fmt.Errorf("没有跳转到统一身份认证登录页（停在 %s）", page.Request.URL)
	}
	pageBody, _ := io.ReadAll(page.Body)
	m := regexp.MustCompile("VERSION:\\s*'portal-fe-([^']+)'").FindSubmatch(pageBody)
	fe := ""
	if len(m) > 1 {
		fe = string(m[1])
	}
	payload := map[string]string{"account": strings.TrimSpace(account), "password": EncryptPassword(password), "login_scene": "feilian", "account_type": "userid"}
	data, _ := json.Marshal(payload)
	req, _ := http.NewRequest("POST", IAM+"/api/v1/login?os=web&t="+fmt.Sprint(time.Now().UnixMilli()), bytes.NewReader(data))
	req.Header.Set("content-type", "application/json")
	req.Header.Set("Accept-Language", "zh")
	req.Header.Set("Page-Name", "portal")
	req.Header.Set("X-Version-Check", "0")
	req.Header.Set("X-Fe-Version", fe)
	resp, err := c.Do(req)
	if err != nil {
		return Session{}, err
	}
	var result struct {
		Message string `json:"message"`
		Data    struct {
			Result string `json:"result"`
			Next   struct {
				Action string `json:"action"`
				Link   string `json:"link"`
			} `json:"next"`
		} `json:"data"`
	}
	if err = json.NewDecoder(resp.Body).Decode(&result); err != nil {
		resp.Body.Close()
		return Session{}, err
	}
	resp.Body.Close()
	if result.Data.Next.Action == "2FA" {
		return Session{}, errors.New("账号需要二次验证，无法自动登录")
	}
	if result.Data.Result != "success" || result.Data.Next.Action != "GoToLink" {
		return Session{}, fmt.Errorf("登录后需要额外步骤：%s", result.Message)
	}
	link := result.Data.Next.Link
	if strings.HasPrefix(link, "/") {
		link = IAM + link
	}
	r, err := c.Get(link)
	if err != nil {
		return Session{}, err
	}
	r.Body.Close()
	body, _ := json.Marshal(map[string]any{"TenantName": "", "Offset": 0, "Limit": 4, "Status": 1})
	req, _ = http.NewRequest("POST", Platform+"/api/iam?Action=ListTenantIDP&Version=2024-12-25", bytes.NewReader(body))
	req.Header.Set("content-type", "application/json")
	req.Header.Set("x-top-region", "cn-north-1")
	resp, err = c.Do(req)
	if err != nil {
		return Session{}, err
	}
	idpBody, readErr := io.ReadAll(resp.Body)
	status := resp.Status
	resp.Body.Close()
	if readErr != nil {
		return Session{}, readErr
	}
	var idps struct {
		Result struct {
			List []struct {
				IDPType string `json:"IDPType"`
				ID      string `json:"Id"`
			} `json:"List"`
		} `json:"Result"`
	}
	if err = json.Unmarshal(idpBody, &idps); err != nil {
		return Session{}, fmt.Errorf("ListTenantIDP 返回非 JSON（HTTP %s）", status)
	}
	if resp.StatusCode >= http.StatusBadRequest {
		return Session{}, fmt.Errorf("ListTenantIDP 请求失败（HTTP %s）：%s", status, compactBody(idpBody))
	}
	if len(idps.Result.List) == 0 {
		return Session{}, fmt.Errorf("平台没有返回 OAuth 身份提供方（HTTP %s）：%s", status, compactBody(idpBody))
	}
	id := ""
	for _, v := range idps.Result.List {
		if v.IDPType == "oauth" {
			id = v.ID
			break
		}
	}
	if id == "" {
		return Session{}, errors.New("平台没有返回 OAuth 身份提供方")
	}
	body, _ = json.Marshal(map[string]string{"SSO": "Oauth", "IdpID": id, "RedirectUrl": Platform + "/"})
	resp, err = c.Post(Platform+"/api/auth/login", "application/json", bytes.NewReader(body))
	if err != nil {
		return Session{}, err
	}
	authBody, readErr := io.ReadAll(resp.Body)
	status = resp.Status
	resp.Body.Close()
	if readErr != nil {
		return Session{}, readErr
	}
	var authResult map[string]any
	if err = json.Unmarshal(authBody, &authResult); err != nil {
		return Session{}, fmt.Errorf("/api/auth/login 返回非 JSON（HTTP %s）", status)
	}
	redirect := findRedirect(authResult)
	if redirect == "" {
		return Session{}, fmt.Errorf("/api/auth/login 没有返回 redirect_uri（HTTP %s）：%s", status, compactBody(authBody))
	}
	r, err = c.Get(redirect)
	if err != nil {
		return Session{}, err
	}
	r.Body.Close()
	var cookies []string
	csrf := ""
	for _, ck := range jar.Cookies(&url.URL{Scheme: "https", Host: "coze.nankai.edu.cn"}) {
		cookies = append(cookies, ck.Name+"="+ck.Value)
		if ck.Name == "x-csrf-token" {
			csrf = ck.Value
		}
	}
	if csrf == "" {
		return Session{}, errors.New("平台没有下发 x-csrf-token")
	}
	return Session{Cookie: strings.Join(cookies, "; "), CSRF: csrf}, nil
}

func compactBody(body []byte) string {
	s := strings.Join(strings.Fields(string(body)), " ")
	if len(s) > 500 {
		return s[:500] + "..."
	}
	return s
}

func findRedirect(v map[string]any) string {
	if s, ok := v["redirect_uri"].(string); ok {
		return s
	}
	for _, key := range []string{"Result", "result", "Data", "data"} {
		if nested, ok := v[key].(map[string]any); ok {
			if s := findRedirect(nested); s != "" {
				return s
			}
		}
	}
	return ""
}
