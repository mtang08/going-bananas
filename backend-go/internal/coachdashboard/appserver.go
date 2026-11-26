package coachdashboard

import (
	"context"
	"errors"
	"io"
	"reflect"
	"time"
)

const (
	coachModel  = "gpt-6-astra"
	coachEffort = "medium"
	profile     = "going_bananas_coach"
	namespace   = "going_bananas"
)

var (
	modelProblem   = &Problem{"model_unavailable", "Astra Medium is unavailable for this Codex account. Check the account and workspace model access."}
	profileProblem = &Problem{"turn_failed", "Codex could not use the dashboard's restricted permissions. Check the Codex installation."}
	authProblem    = &Problem{"auth_required", "Sign in with ChatGPT to use the coach."}
)

type ToolDefinition struct {
	Name, Description string
	InputSchema       Object
}

// DashboardTools binds each call to its server-issued dashboard turn ID. Its
// implementation checks active-turn ownership before transactional tool work.
type DashboardTools interface {
	Definitions() []ToolDefinition
	Call(ctx context.Context, turnID, name string, arguments Object) (Object, error)
}

// StdioAppServer opens an isolated local process per turn. The caller supplies
// the restricted launcher, trusted instructions and review-scoped tools.
type StdioAppServer struct {
	Open                    func(context.Context) (io.ReadWriteCloser, error)
	Workspace, Instructions string
	LoadInstructions        func() (string, error)
	Tools                   DashboardTools
}

func allowedTool(name string) bool {
	switch name {
	case "active_proposal", "review_findings", "coaching_snapshot", "coaching_query", "proposal_schema", "save_pending_proposal":
		return true
	}
	return false
}

func (s *StdioAppServer) RunTurn(ctx context.Context, req TurnRequest) (reply string, err error) {
	instructions := s.Instructions
	if s.LoadInstructions != nil {
		instructions, err = s.LoadInstructions()
		if err != nil {
			return "", err
		}
	}
	if s.Open == nil || s.Tools == nil || instructions == "" || s.Workspace == "" || req.TurnID == "" {
		return "", errors.New("incomplete dashboard runtime configuration")
	}
	tools := s.Tools.Definitions()
	names := make(map[string]bool, len(tools))
	var defs []Object
	for _, d := range tools {
		if !allowedTool(d.Name) || names[d.Name] || d.InputSchema == nil {
			return "", errors.New("invalid dashboard tool definition")
		}
		names[d.Name] = true
		defs = append(defs, Object{"type": "function", "name": d.Name, "description": d.Description, "inputSchema": d.InputSchema})
	}
	ctx, cancel := context.WithTimeout(ctx, 5*time.Minute)
	defer cancel()
	defer func() {
		if errors.Is(err, context.DeadlineExceeded) {
			err = &Problem{"timeout", "The coach took too long to reply. Try again."}
		}
	}()
	stream, err := s.Open(ctx)
	if err != nil {
		return "", err
	}
	r, err := OpenRPC(ctx, stream)
	if err != nil {
		return "", err
	}
	defer r.Close()
	if err := requireModel(ctx, r); err != nil {
		return "", err
	}
	thread, err := s.openThread(ctx, r, req.ThreadID, instructions, defs)
	if err != nil {
		return "", err
	}
	res, err := r.Request(ctx, "turn/start", Object{"threadId": thread, "input": []Object{{"type": "text", "text": req.Message, "text_elements": []string{}}}, "model": coachModel, "effort": coachEffort, "approvalPolicy": "never", "permissions": profile, "environments": []string{}, "runtimeWorkspaceRoots": []string{}})
	if err != nil {
		return "", err
	}
	active := turnIdentity{thread: thread, turn: idOf(res["turn"])}
	if active.turn == "" {
		return "", errors.New("missing runtime turn ID")
	}
	defer func() {
		if err != nil {
			interrupt(r, active)
		}
	}()
	if req.ThreadID == "" {
		if err := req.OnThread(thread); err != nil {
			return "", err
		}
	}
	return s.stream(ctx, r, req, active, names)
}

func object(v any) Object             { obj, _ := v.(Object); return obj }
func field(o Object, k string) string { v, _ := o[k].(string); return v }
func idOf(v any) string               { return field(object(v), "id") }
func array(v any) []any               { a, _ := v.([]any); return a }

func requireModel(ctx context.Context, r *RPC) error {
	account, err := r.Request(ctx, "account/read", Object{"refreshToken": false})
	if err != nil {
		return err
	}
	if field(object(account["account"]), "type") != "chatgpt" {
		return authProblem
	}
	params := Object{"modelProvider": "openai", "includeHidden": true, "limit": 100}
	seen := map[string]bool{}
	for {
		models, err := r.Request(ctx, "model/list", params)
		if err != nil {
			return err
		}
		for _, m := range array(models["data"]) {
			if field(object(m), "model") != coachModel {
				continue
			}
			for _, e := range array(object(m)["supportedReasoningEfforts"]) {
				if field(object(e), "reasoningEffort") == coachEffort {
					return nil
				}
			}
		}
		next := field(models, "nextCursor")
		if next == "" || seen[next] {
			return modelProblem
		}
		seen[next] = true
		params["cursor"] = next
	}
}

func (s *StdioAppServer) openThread(ctx context.Context, r *RPC, thread, instructions string, defs []Object) (string, error) {
	params := Object{"cwd": s.Workspace, "model": coachModel, "modelProvider": "openai", "permissions": profile, "approvalPolicy": "never", "runtimeWorkspaceRoots": []string{}, "developerInstructions": instructions}
	method := "thread/start"
	if thread == "" {
		params["allowProviderModelFallback"] = false
		params["environments"] = []string{}
		params["ephemeral"] = false
		params["dynamicTools"] = []Object{{"type": "namespace", "name": namespace, "description": "Read filtered Going Bananas training evidence and save pending proposals.", "tools": defs}}
	} else {
		method = "thread/resume"
		params["threadId"] = thread
		params["excludeTurns"] = true
	}
	result, err := r.Request(ctx, method, params)
	if err != nil {
		return "", err
	}
	if field(result, "model") != coachModel || field(result, "reasoningEffort") != coachEffort {
		return "", modelProblem
	}
	expected := Object{"cwd": s.Workspace, "modelProvider": "openai", "approvalPolicy": "never", "runtimeWorkspaceRoots": []any{}, "instructionSources": []any{}, "activePermissionProfile": Object{"id": profile, "extends": nil}, "sandbox": Object{"type": "readOnly", "networkAccess": false}}
	for k, v := range expected {
		if !reflect.DeepEqual(result[k], v) {
			return "", profileProblem
		}
	}
	current := idOf(result["thread"])
	if current == "" || object(result["thread"])["ephemeral"] != false || (thread != "" && current != thread) {
		return "", errors.New("invalid runtime thread identity")
	}
	return current, nil
}

type turnIdentity struct{ thread, turn string }

func (a turnIdentity) matches(d Object) bool {
	id := field(d, "turnId")
	if id == "" {
		id = idOf(d["turn"])
	}
	return field(d, "threadId") == a.thread && id == a.turn
}

func interrupt(r *RPC, a turnIdentity) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if _, err := r.Request(ctx, "turn/interrupt", Object{"threadId": a.thread, "turnId": a.turn}); err != nil {
		return
	}
	for {
		e, err := r.Event(ctx)
		if err != nil {
			return
		}
		if _, ok := e["id"]; ok {
			if reject(ctx, r, e) != nil {
				return
			}
			continue
		}
		if field(e, "method") == "turn/completed" && a.matches(object(e["params"])) {
			return
		}
	}
}

func reject(ctx context.Context, r *RPC, e Object) error {
	return r.Send(ctx, Object{"id": e["id"], "error": Object{"code": -32601, "message": "This dashboard capability is unavailable."}})
}
