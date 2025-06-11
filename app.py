import os
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

app = FastAPI()

GOODREADS_RSS_URL = os.getenv("GOODREADS_RSS_URL")

@app.get("/")
def read_root():
    if GOODREADS_RSS_URL:
        return PlainTextResponse(f"RSS URL is: {GOODREADS_RSS_URL}")
    else:
        return PlainTextResponse("No RSS URL provided.")
