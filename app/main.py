from fastapi import FastAPI

app = FastAPI(
    title="TeacherHub Backend",
    version="0.1.0"
)

@app.get("/")
def root():
    return {"message": "TeacherHub API"}