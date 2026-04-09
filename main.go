package main

import (
	"fmt"
	"log"
	"net/http"
	"os"

	"github.com/gorilla/mux"
)

func main() {
	router := mux.NewRouter()
	router.HandleFunc("/", Handler).Methods("GET")
	log.Fatal(http.ListenAndServe(":8080", router))
}

// If the TIMESTAMP env var is set, it responds with "Hello from $TIMESTAMP",
// otherwise it responds with "Hello from the beginning of Golang Time".
func Handler(w http.ResponseWriter, r *http.Request) {
	if ts := os.Getenv("TIMESTAMP"); ts != "" {
		fmt.Fprintf(w, "Hello from %s\n", ts)
	} else {
		fmt.Fprintln(w, "Hello from the beginning of Golang Time")
	}
}
