from run_benchmark import (
    load_dataset,
    MODELS,
    call_gpt,
    call_claude,
    call_gemini,
)


def main():
    dataset = load_dataset()
    item = dataset[0]

    case_id = item["caseId"]
    message = item["message"]

    print("=" * 60)
    print("LLM API 연결 테스트")
    print("=" * 60)
    print(f"Case: {case_id}")
    print(f"Message: {message}")
    print()

    tests = [
        ("GPT", call_gpt),
        ("Claude", call_claude),
        ("Gemini", call_gemini),
    ]

    for model_name, call_function in tests:
        print("-" * 60)
        print(f"[{model_name}]")
        print(f"Model: {MODELS[model_name]}")

        try:
            result = call_function(message)

            print("STATUS: SUCCESS")
            print(f"Latency: {result['latency_ms']:.2f} ms")
            print(f"Input tokens: {result['input_tokens']}")
            print(f"Output tokens: {result['output_tokens']}")
            print("Response:")
            print(result["text"])

        except Exception as e:
            print("STATUS: FAILED")
            print(f"Error: {type(e).__name__}")
            print(f"Message: {e}")

    print()
    print("=" * 60)
    print("테스트 종료")
    print("=" * 60)


if __name__ == "__main__":
    main()
