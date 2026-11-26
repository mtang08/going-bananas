package coachdashboard

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"strconv"
	"time"
	"unicode/utf8"
)

type Object = map[string]any

const maxFrame = 4 << 20

type rpcEvent struct {
	object Object
	size   int
}
type writeFrame struct {
	data []byte
	done chan error
}

// RPC is a single-consumer stdio session. Closing its stream must unblock I/O.
type RPC struct {
	stream       io.ReadWriteCloser
	incoming     chan rpcEvent
	writes       chan writeFrame
	done         chan struct{}
	sequence     int
	pending      []rpcEvent
	pendingBytes int
}

func OpenRPC(ctx context.Context, stream io.ReadWriteCloser) (*RPC, error) {
	r := &RPC{stream: stream, incoming: make(chan rpcEvent), writes: make(chan writeFrame), done: make(chan struct{})}
	go r.readFrames()
	go r.writeFrames()
	_, err := r.Request(ctx, "initialize", Object{"clientInfo": Object{"name": "going_bananas_coach", "title": "Going Bananas Coach", "version": "1.0"}, "capabilities": Object{"experimentalApi": true}})
	if err == nil {
		err = r.Send(ctx, Object{"method": "initialized"})
	}
	if err != nil {
		r.Close()
		return nil, err
	}
	return r, nil
}

func (r *RPC) Close() { close(r.done); _ = r.stream.Close() }

func (r *RPC) readFrames() {
	defer close(r.incoming)
	sc := bufio.NewScanner(r.stream)
	sc.Buffer(make([]byte, 8192), maxFrame+1)
	for sc.Scan() {
		line := sc.Bytes()
		var obj Object
		decoder := json.NewDecoder(bytes.NewReader(line))
		decoder.UseNumber()
		err := decoder.Decode(&obj)
		if err != nil || obj == nil || !utf8.Valid(line) || !json.Valid(line) {
			return
		}
		select {
		case r.incoming <- rpcEvent{object: obj, size: len(line)}:
		case <-r.done:
			return
		}
	}
}

func (r *RPC) writeFrames() {
	for {
		select {
		case <-r.done:
			return
		case frame := <-r.writes:
			_, err := r.stream.Write(frame.data)
			frame.done <- err
		}
	}
}

func (r *RPC) Send(ctx context.Context, o Object) error {
	data, err := json.Marshal(o)
	if err != nil || len(data) > maxFrame {
		return errors.New("invalid outbound app-server frame")
	}
	f := writeFrame{append(data, '\n'), make(chan error, 1)}
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-r.done:
		return io.ErrClosedPipe
	case r.writes <- f:
	}
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-r.done:
		return io.ErrClosedPipe
	case err := <-f.done:
		return err
	}
}

func (r *RPC) receive(ctx context.Context) (rpcEvent, error) {
	select {
	case <-ctx.Done():
		return rpcEvent{}, ctx.Err()
	case e, ok := <-r.incoming:
		if !ok {
			return rpcEvent{}, errors.New("app-server stream closed or invalid frame")
		}
		return e, nil
	}
}

func (r *RPC) Event(ctx context.Context) (Object, error) {
	if len(r.pending) > 0 {
		e := r.pending[0]
		r.pending[0] = rpcEvent{}
		r.pending = r.pending[1:]
		r.pendingBytes -= e.size
		return e.object, nil
	}
	e, err := r.receive(ctx)
	return e.object, err
}

func (r *RPC) Request(parent context.Context, method string, params Object) (result Object, err error) {
	ctx, cancel := context.WithTimeout(parent, 30*time.Second)
	defer cancel()
	defer func() {
		if errors.Is(err, context.DeadlineExceeded) && parent.Err() == nil {
			err = &Problem{"timeout", "The local Codex App Server took too long to respond. Try again."}
		}
	}()
	r.sequence++
	id := r.sequence
	if err := r.Send(ctx, Object{"method": method, "id": id, "params": params}); err != nil {
		return nil, err
	}
	for {
		e, err := r.receive(ctx)
		if err != nil {
			return nil, err
		}
		if _, ok := e.object["method"]; ok {
			if len(r.pending) >= 2048 || r.pendingBytes+e.size > 2*maxFrame {
				return nil, errors.New("app-server event queue full")
			}
			r.pending = append(r.pending, e)
			r.pendingBytes += e.size
			continue
		}
		if e.object["id"] != json.Number(strconv.Itoa(id)) {
			continue
		}
		result, ok := e.object["result"].(Object)
		if !ok {
			switch method {
			case "thread/resume":
				return nil, &Problem{"turn_failed", "Codex could not reopen this conversation. Try again or start a new chat."}
			case "account/login/start":
				return nil, &Problem{"auth_required", "Codex could not start ChatGPT sign-in. Try again."}
			default:
				return nil, &Problem{"turn_failed", "The local Codex App Server could not process this request. Try again."}
			}
		}
		return result, nil
	}
}
