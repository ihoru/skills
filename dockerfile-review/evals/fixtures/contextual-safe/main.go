package main

import (
	"log"
	"net/http"
)

var buildInput string

func healthcheck(response http.ResponseWriter, _ *http.Request) {
	if buildInput == "" {
		http.Error(response, "missing build input", http.StatusServiceUnavailable)
		return
	}
	response.WriteHeader(http.StatusNoContent)
}

func main() {
	http.HandleFunc("/health", healthcheck)
	log.Fatal(http.ListenAndServe(":8080", nil))
}
