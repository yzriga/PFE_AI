from rag.query import ask_with_citations

if __name__ == "__main__":
    question = "What is the main contribution of the paper?"
    result = ask_with_citations(question)

    print("\n🧠 ANSWER:\n")
    print(result["answer"])

    print("\n📚 SOURCES:\n")
    for c in result["citations"]:
        print("-", c)

