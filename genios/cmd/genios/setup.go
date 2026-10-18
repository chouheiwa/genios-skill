package main

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	g "genios/internal/genios"
	"html/template"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

const setupPage = `<!doctype html><meta charset="utf-8"><title>GeniOS 登录</title>
<style>body{font:16px system-ui;max-width:560px;margin:48px auto;padding:0 20px}label{display:block;margin:18px 0 6px}input{box-sizing:border-box;width:100%;padding:10px;font-size:16px}button{margin-top:22px;padding:10px 18px;font-size:16px}p{white-space:pre-wrap}.ok{color:#087f23}.err{color:#b00020}</style>
<h1>GeniOS 登录管理</h1><p>账号和密码只提交给本机运行的 genios，不会发送给网页之外的服务。</p>
<form method="post"><label>统一身份认证账号</label><input name="account" autocomplete="username" required value="{{.Account}}"><label>密码</label><input type="password" name="password" autocomplete="current-password" required><button>登录并保存</button></form>{{if .Message}}<p class="{{.Class}}">{{.Message}}</p>{{end}}`

type setupData struct{ Account, Message, Class string }

func setup(a []string) {
	port := "0"
	for i := 0; i < len(a); i++ {
		if a[i] == "--port" && i+1 < len(a) {
			port = a[i+1]
			i++
		}
	}
	ln, e := net.Listen("tcp", "127.0.0.1:"+port)
	if e != nil {
		fatal(e.Error())
	}
	defer ln.Close()
	tokenBytes := make([]byte, 16)
	if _, e = rand.Read(tokenBytes); e != nil {
		fatal(e.Error())
	}
	token := hex.EncodeToString(tokenBytes)
	tmpl := template.Must(template.New("setup").Parse(setupPage))
	mux := http.NewServeMux()
	current := setupData{}
	mux.HandleFunc("/setup/"+token, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			current.Account = ""
			current.Message = ""
			_ = tmpl.Execute(w, current)
			return
		}
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", 405)
			return
		}
		if e := r.ParseForm(); e != nil {
			http.Error(w, e.Error(), 400)
			return
		}
		account := strings.TrimSpace(r.FormValue("account"))
		password := r.FormValue("password")
		current = setupData{Account: account}
		if account == "" || password == "" {
			current.Message = "账号和密码不能为空"
			current.Class = "err"
			_ = tmpl.Execute(w, current)
			return
		}
		session, e := g.Login(account, password)
		if e != nil {
			current.Message = "登录失败：" + e.Error()
			current.Class = "err"
			_ = tmpl.Execute(w, current)
			return
		}
		path := g.CredentialsPath()
		if e = saveCredentials(path, account, password); e != nil {
			current.Message = "登录成功，但凭据保存失败：" + e.Error()
			current.Class = "err"
			_ = tmpl.Execute(w, current)
			return
		}
		sessionPath := g.SessionPath()
		if sessionPath == "" {
			current.Message = "登录成功，但未设置 GENIOS_SESSION_FILE，无法保存会话"
			current.Class = "err"
			_ = tmpl.Execute(w, current)
			return
		}
		if e = g.WriteSession(session, sessionPath); e != nil {
			current.Message = "登录成功，但会话保存失败：" + e.Error()
			current.Class = "err"
			_ = tmpl.Execute(w, current)
			return
		}
		current.Message = "登录成功。凭据已保存到 " + path + "，会话已保存到 " + sessionPath
		current.Class = "ok"
		_ = tmpl.Execute(w, current)
	})
	url := "http://" + ln.Addr().String() + "/setup/" + token
	fmt.Println("请在浏览器打开：", url)
	fmt.Println("按 Ctrl-C 停止本地管理页面")
	if e = http.Serve(ln, mux); e != nil && e != http.ErrServerClosed {
		fatal(e.Error())
	}
}
func saveCredentials(path, account, password string) error {
	if e := os.MkdirAll(filepath.Dir(path), 0700); e != nil {
		return e
	}
	f, e := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0600)
	if e != nil {
		return e
	}
	defer f.Close()
	_, e = fmt.Fprintf(f, "ACCOUNT=%s\nPASSWORD=%s\n", account, password)
	return e
}
