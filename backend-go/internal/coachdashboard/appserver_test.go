package coachdashboard

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"slices"
	"strings"
	"testing"
	"time"
)

type testCoachTools struct{ calls []string }

func (*testCoachTools) Definitions() []ToolDefinition {
	var defs []ToolDefinition
	for _, n := range []string{"active_proposal", "review_findings", "coaching_snapshot", "coaching_query", "proposal_schema", "save_pending_proposal"} {
		defs = append(defs, ToolDefinition{Name: n, InputSchema: Object{"type": "object"}})
	}
	return defs
}
func (t *testCoachTools) Call(_ context.Context, id, name string, _ Object) (Object, error) {
	if id != "dashboard-turn" {
		return nil, errors.New("wrong dashboard turn")
	}
	t.calls = append(t.calls, name)
	return Object{"ok": true}, nil
}

type peer struct {
	d   *json.Decoder
	e   *json.Encoder
	err error
}

func (p *peer) read() Object {
	var v Object
	if p.err == nil {
		p.err = p.d.Decode(&v)
	}
	return v
}
func (p *peer) send(obj Object) {
	if p.err == nil {
		p.err = p.e.Encode(obj)
	}
}
func (p *peer) expect(ok bool, where string) {
	if !ok && p.err == nil {
		p.err = fmt.Errorf("unexpected frame at %s", where)
	}
}
func (p *peer) request(method string, result Object) Object {
	v := p.read()
	p.expect(field(v, "method") == method, method)
	if result != nil {
		p.send(Object{"id": v["id"], "result": result})
	}
	return object(v["params"])
}

func scriptedHandshake(p *peer, resume bool, profileOverride Object) {
	p.request("initialize", Object{})
	p.request("initialized", nil)
	p.request("account/read", Object{"account": Object{"type": "chatgpt"}})
	p.request("model/list", Object{"data": []Object{}, "nextCursor": "another"})
	q := p.request("model/list", Object{"data": []Object{{"model": coachModel, "supportedReasoningEfforts": []Object{{"reasoningEffort": coachEffort}}}}})
	p.expect(q["cursor"] == "another", "model pagination")
	result := Object{"thread": Object{"id": "thread", "ephemeral": false}, "model": coachModel, "reasoningEffort": coachEffort, "cwd": "/coach", "modelProvider": "openai", "approvalPolicy": "never", "runtimeWorkspaceRoots": []string{}, "instructionSources": []string{}, "activePermissionProfile": Object{"id": profile, "extends": nil}, "sandbox": Object{"type": "readOnly", "networkAccess": false}}
	for k, v := range profileOverride {
		result[k] = v
	}
	if resume {
		q = p.request("thread/resume", result)
		p.expect(q["threadId"] == "thread" && q["excludeTurns"] == true, "resume ID")
	} else {
		q = p.request("thread/start", result)
		spaces := array(q["dynamicTools"])
		p.expect(len(spaces) == 1 && len(array(object(spaces[0])["tools"])) == 6, "tool definitions")
	}
}

func notification(method string, extra Object) Object {
	v := Object{"threadId": "thread", "turnId": "turn"}
	for k, val := range extra {
		v[k] = val
	}
	return Object{"method": method, "params": v}
}
func setupPeer(t *testing.T, script func(*peer)) (*StdioAppServer, *testCoachTools, <-chan error) {
	t.Helper()
	c, s := net.Pipe()
	_ = s.SetDeadline(time.Now().Add(5 * time.Second))
	t.Cleanup(func() { _ = c.Close(); _ = s.Close() })
	done := make(chan error, 1)
	go func() {
		defer func() { _ = s.Close() }()
		p := &peer{d: json.NewDecoder(s), e: json.NewEncoder(s)}
		script(p)
		done <- p.err
	}()
	tools := &testCoachTools{}
	runtime := &StdioAppServer{Workspace: "/coach", Instructions: "synthetic instructions", Tools: tools, Open: func(context.Context) (io.ReadWriteCloser, error) { return c, nil }}
	return runtime, tools, done
}

func TestAppServerWireReviewAndResume(t *testing.T) {
	for _, resume := range []bool{false, true} {
		t.Run(fmt.Sprintf("resume_%t", resume), func(t *testing.T) {
			runtime, tools, done := setupPeer(t, func(p *peer) {
				scriptedHandshake(p, resume, nil)
				start := p.read()
				p.expect(field(start, "method") == "turn/start", "turn/start")
				item := Object{"type": "agentMessage", "id": "answer", "phase": "final_answer"}
				p.send(notification("item/started", Object{"item": item}))
				p.send(Object{"id": start["id"], "result": Object{"turn": Object{"id": "turn"}}})
				for _, tool := range (&testCoachTools{}).Definitions() {
					call := notification("item/tool/call", Object{"namespace": namespace, "tool": tool.Name, "arguments": Object{}})
					call["id"] = "server-id"
					p.send(call)
					reply := p.read()
					p.expect(reply["id"] == "server-id" && object(reply["result"])["success"] == true, tool.Name)
				}
				for _, d := range []Object{{"tool": "accept_proposal", "namespace": namespace}, {"tool": "active_proposal", "namespace": "other"}} {
					d["arguments"] = Object{}
					call := notification("item/tool/call", d)
					call["id"] = 42
					p.send(call)
					p.expect(object(p.read()["result"])["success"] == false, "reject forbidden tool")
				}
				request := notification("item/commandExecution/requestApproval", nil)
				request["id"] = "approval"
				p.send(request)
				p.expect(object(p.read()["error"])["code"] == float64(-32601), "reject approval")
				p.send(notification("item/agentMessage/delta", Object{"itemId": "answer", "delta": "Hel"}))
				p.send(notification("item/agentMessage/delta", Object{"threadId": "other", "itemId": "answer", "delta": "mismatch"}))
				p.send(notification("item/completed", Object{"item": Object{"id": "progress", "type": "agentMessage", "phase": "commentary", "text": "internal"}}))
				item["text"] = "Hello"
				p.send(notification("item/completed", Object{"item": item}))
				p.send(notification("turn/completed", Object{"turn": Object{"status": "completed", "id": "turn", "items": []Object{item}}}))
			})
			thread := ""
			if resume {
				thread = "thread"
			}
			var deltas []string
			saved := ""
			reply, err := runtime.RunTurn(t.Context(), TurnRequest{TurnID: "dashboard-turn", Message: "athlete text", ThreadID: thread, OnThread: func(s string) error { saved = s; return nil }, OnDelta: func(s string) error { deltas = append(deltas, s); return nil }})
			if peerErr := <-done; peerErr != nil {
				t.Fatal(peerErr)
			}
			if err != nil || reply != "Hello" || !slices.Equal(deltas, []string{"Hel", "lo"}) || len(tools.calls) != 6 || (!resume && saved != "thread") || (resume && saved != "") {
				t.Fatalf("reply=%q delta=%q saved=%q calls=%v error=%v", reply, deltas, saved, tools.calls, err)
			}
		})
	}
}

func TestAppServerInterruptsActiveTurn(t *testing.T) {
	ctx, cancel := context.WithCancel(t.Context())
	defer cancel()
	runtime, _, done := setupPeer(t, func(p *peer) {
		scriptedHandshake(p, false, nil)
		p.request("turn/start", Object{"turn": Object{"id": "turn"}})
		p.request("turn/interrupt", Object{})
		p.send(notification("turn/completed", Object{"turn": Object{"status": "interrupted", "id": "turn"}}))
	})
	_, err := runtime.RunTurn(ctx, TurnRequest{TurnID: "dashboard-turn", OnThread: func(string) error { cancel(); return nil }})
	if peerErr := <-done; peerErr != nil {
		t.Fatal(peerErr)
	}
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("got %v", err)
	}
}

func TestAppServerRejectsUnrestrictedProfile(t *testing.T) {
	runtime, _, done := setupPeer(t, func(p *peer) {
		scriptedHandshake(p, false, Object{"sandbox": Object{"type": "readOnly", "networkAccess": true}})
	})
	_, err := runtime.RunTurn(t.Context(), TurnRequest{TurnID: "dashboard-turn"})
	if peerErr := <-done; peerErr != nil {
		t.Fatal(peerErr)
	}
	if !errors.Is(err, profileProblem) {
		t.Fatalf("got %v", err)
	}
}

func TestRPCRejectsOversizedAndMalformedFrames(t *testing.T) {
	for _, line := range []string{strings.Repeat("a", maxFrame+1), "[]", "{}{}", "\xff"} {
		c, s := net.Pipe()
		go func() {
			defer func() { _ = s.Close() }()
			var request Object
			_ = json.NewDecoder(s).Decode(&request)
			_, _ = io.WriteString(s, line+"\n")
		}()
		if _, err := OpenRPC(t.Context(), c); err == nil {
			t.Fatal("accepted invalid frame")
		}
	}
}
