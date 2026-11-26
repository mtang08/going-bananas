// Command garmin-replay applies downloaded fixture pages to a synthetic workspace.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/replay"
)

type delivery struct {
	JobID        uuid.UUID         `json:"job_id"`
	Index        int               `json:"index"`
	Final        bool              `json:"final"`
	FetchedAt    time.Time         `json:"fetched_at"`
	AccountScope string            `json:"account_scope"`
	ActivityPage string            `json:"activity_page"`
	Activities   []map[string]any  `json:"activities"`
	Export       string            `json:"export"`
	FIT          map[string]string `json:"fit"`
}

func load(path string) (replay.Page, error) {
	var page replay.Page
	f, err := os.Open(path)
	if err != nil {
		return page, err
	}
	defer func() { _ = f.Close() }()
	var d delivery
	dec := json.NewDecoder(f)
	dec.UseNumber()
	dec.DisallowUnknownFields()
	if err := dec.Decode(&d); err != nil {
		return page, err
	}
	if err := dec.Decode(new(any)); !errors.Is(err, io.EOF) {
		return page, errors.New("unexpected trailing manifest content")
	}
	page = replay.Page{JobID: d.JobID, Index: d.Index, Final: d.Final, FetchedAt: d.FetchedAt, AccountScope: d.AccountScope, SourceKind: "garmin_api", FIT: map[string][]byte{}}
	read := func(file string) ([]byte, error) {
		if !filepath.IsLocal(file) {
			return nil, errors.New("manifest attachments must be relative paths")
		}
		return os.ReadFile(filepath.Join(filepath.Dir(path), file))
	}
	if d.ActivityPage != "" {
		if d.Activities != nil || d.Export != "" {
			return page, errors.New("choose one activity page or export input")
		}
		body, err := read(d.ActivityPage)
		if err != nil {
			return page, err
		}
		if !json.Valid(body) {
			return page, errors.New("invalid downloaded activity page")
		}
		dec := json.NewDecoder(bytes.NewReader(body))
		dec.UseNumber()
		if err := dec.Decode(&d.Activities); err != nil || d.Activities == nil {
			return page, errors.New("downloaded activity page must be an array of records")
		}
	}
	if d.Export != "" {
		if d.Activities != nil {
			return page, errors.New("choose either a downloaded API page or an export archive")
		}
		page.ExportArchive, err = read(d.Export)
		if err != nil {
			return page, err
		}
		scan, err := replay.ScanExport(page.ExportArchive)
		if err != nil {
			return page, err
		}
		scope := "garmin-owner:" + scan.Owner
		if d.AccountScope != "" && d.AccountScope != "auto" && d.AccountScope != scope {
			return page, errors.New("mixed_source_account")
		}
		page.Records, page.ExportMember, page.AccountScope, page.SourceKind = scan.Records, scan.MemberBytes, scope, "garmin_export"
	} else {
		for _, r := range d.Activities {
			page.Records = append(page.Records, replay.ActivityRecord{Record: r})
		}
	}
	for id, file := range d.FIT {
		b, err := read(file)
		if err != nil {
			return page, err
		}
		page.FIT[id] = b
	}
	return page, nil
}

func run() error {
	manifest := flag.String("page", "", "path to synthetic replay manifest")
	reprocess := flag.String("reprocess", "", "activity UUID for retained archive reprocessing")
	flag.Parse()
	if (*manifest == "") == (*reprocess == "") || flag.NArg() != 0 {
		return errors.New("use -page <manifest.json> or -reprocess <activity-uuid>")
	}
	mode, root := os.Getenv("APP_MODE"), os.Getenv("PRIVATE_DIR")
	if (mode != "test" && mode != "demo") || root == "" {
		return errors.New("select a test or demo workspace with PRIVATE_DIR")
	}
	dsn := strings.Replace(os.Getenv("DATABASE_URL"), "postgresql+psycopg://", "postgresql://", 1)
	u, err := url.Parse(dsn)
	if err != nil || (u.Scheme != "postgresql" && u.Scheme != "postgres") {
		return errors.New("invalid synthetic DATABASE_URL")
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil || !strings.HasSuffix(cfg.ConnConfig.Database, "_"+mode) {
		return errors.New("database name must match synthetic mode")
	}
	ctx := context.Background()
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return errors.New("cannot open synthetic database")
	}
	defer pool.Close()
	if *reprocess != "" {
		id, err := uuid.Parse(*reprocess)
		if err != nil {
			return errors.New("invalid activity UUID")
		}
		status, err := replay.Reprocess(ctx, pool, root, id)
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(map[string]string{"status": status})
	}
	page, err := load(*manifest)
	if err != nil {
		return err
	}
	res, err := replay.Apply(ctx, pool, root, page)
	if err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(res)
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
