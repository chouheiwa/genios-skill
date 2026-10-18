package main

import (
	"encoding/json"
	"flag"
	"fmt"
	g "genios/internal/genios"
	"os"
	"path/filepath"
	"strings"
)

func main() {
	if len(os.Args) < 2 {
		usage()
		return
	}
	switch os.Args[1] {
	case "auth":
		auth(os.Args[2:])
	case "setup":
		setup(os.Args[2:])
	case "api":
		api(os.Args[2:])
	case "chat":
		chat(os.Args[2:])
	case "flow":
		flow(os.Args[2:])
	case "qa":
		if len(os.Args) < 3 || os.Args[2] != "upload" {
			fatal("用法：genios qa upload ...")
		}
		qa(os.Args[3:])
	case "debug":
		debug(os.Args[2:])
	case "traces":
		traces(os.Args[2:])
	case "publish":
		publish(os.Args[2:])
	default:
		usage()
		os.Exit(2)
	}
}
func usage() {
	fmt.Println("genios setup|auth|api|chat|flow|qa|debug|traces|publish\n  setup                         在本机网页管理账号和密码\n  auth [--credentials FILE]     登录并保存 session\n  api ACTION [JSON] [--service app]\n  chat stream|block TEXT\n  flow check|run|reset|add|set|link ...\n  qa upload ... | debug ... | traces ... | publish ...")
}
func auth(a []string) {
	f := flag.NewFlagSet("auth", flag.ExitOnError)
	cred := f.String("credentials", g.CredentialsPath(), "credentials file")
	sess := f.String("session-file", g.SessionPath(), "session file")
	f.Parse(a)
	if *sess == "" {
		fatal("请指定 --session-file 或 GENIOS_SESSION_FILE")
	}
	c, e := g.ReadCredentials(*cred)
	if e == nil {
		var s g.Session
		s, e = g.Login(c.Account, c.Password)
		if e == nil {
			e = g.WriteSession(s, *sess)
		}
	}
	if e != nil {
		fatal(e.Error())
	}
	fmt.Println("登录成功，会话已写入", *sess)
}
func api(a []string) {
	if len(a) < 1 {
		fatal("缺少 Action")
	}
	action := a[0]
	body := map[string]any{}
	svc := "app"
	for i := 1; i < len(a); i++ {
		if a[i] == "--service" && i+1 < len(a) {
			svc = a[i+1]
			i++
			continue
		}
		if !strings.HasPrefix(a[i], "--") {
			if e := json.Unmarshal([]byte(a[i]), &body); e != nil {
				fatal(e.Error())
			}
		}
	}
	ws := g.Workspace()
	if ws == "" {
		fatal("缺少团队空间 ID；请先从 genios-project.md 配置中取 WorkspaceID，并设置 GENIOS_TEAM_WORKSPACE")
	}
	s, e := loadSession()
	if e != nil {
		fatal(e.Error())
	}
	client := g.NewClient(s, ws)
	r, e := client.Call(action, body, svc)
	if e != nil && strings.Contains(e.Error(), "会话失效") {
		cred, ce := g.ReadCredentials(g.CredentialsPath())
		if ce == nil {
			s, ce = g.Login(cred.Account, cred.Password)
			if ce == nil {
				ce = g.WriteSession(s, g.SessionPath())
			}
			if ce == nil {
				r, e = g.NewClient(s, ws).Call(action, body, svc)
			}
		}
	}
	if e != nil {
		fatal(e.Error())
	}
	b, _ := json.MarshalIndent(r, "", "  ")
	fmt.Println(string(b))
}
func chat(a []string) {
	if len(a) < 2 || (a[0] != "stream" && a[0] != "block") {
		fatal("用法：genios chat stream|block 文本")
	}
	c, e := g.NewChatClient()
	if e != nil {
		fatal(e.Error())
	}
	text := strings.Join(a[1:], " ")
	if a[0] == "stream" {
		if e = c.Stream(text, ""); e != nil {
			fatal(e.Error())
		}
		return
	}
	v, e := c.Block(text, "")
	if e != nil {
		fatal(e.Error())
	}
	b, _ := json.MarshalIndent(v, "", "  ")
	fmt.Println(string(b))
}
func fatal(s string) { fmt.Fprintln(os.Stderr, s); os.Exit(1) }

var _ = filepath.Separator
