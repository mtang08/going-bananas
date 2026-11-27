package main

import "testing"

func TestArguments(t *testing.T) {
	for _, args := range [][]string{{"--apply", "sample.csv"}, {"sample.csv", "--apply"}, {"-apply", "--", "sample.csv"}} {
		file, apply, err := options(args)
		if err != nil || !apply || file != "sample.csv" {
			t.Fatalf("args %q: %q, %v, %v", args, file, apply, err)
		}
	}
	file, apply, err := options([]string{"--", "-file.csv"})
	if err != nil || apply || file != "-file.csv" {
		t.Fatal(file, apply, err)
	}
	for _, args := range [][]string{nil, {"one", "two"}, {"--other", "sample.csv"}} {
		if _, _, err := options(args); err == nil {
			t.Fatal(args)
		}
	}
}
