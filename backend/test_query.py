from rag.query import ask_with_citations

if __name__ == "__main__":
    question = "What is the main contribution of the paper?"
    result = ask_with_citations(question)

    print("\nANSWER:\n")
    print(result["answer"])

    print("\nSOURCES:\n")
    for c in result["citations"]:
        print("-", c)

