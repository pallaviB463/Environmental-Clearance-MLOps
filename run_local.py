from agent.graph import graph
from agent.state import (
    AgentState,
    ProjectRequest,
    Capacity,
    Location,
    ProtectedArea
)


def main():

    print("\n" + "=" * 60)
    print("ENVIRONMENTAL CLEARANCE PRE-SCREENING")
    print("=" * 60)

    # --------------------------------------------------
    # TEST CASE
    # Industrial project near a protected area
    # --------------------------------------------------

    request = ProjectRequest(
        run_id="run_001",
        correlation_id="corr_001",

        description=(
            "Industrial project located 2 km "
            "from a national park."
        ),

        sector_hint="industrial",

        capacity=Capacity(
            value=100,
            unit="TPD"
        ),

        area_ha=25,

        location=Location(
            state="Karnataka",
            district="Mysuru"
        ),

        nearest_protected_area=ProtectedArea(
            type="national_park",
            distance_km=2
        )
    )

    initial_state = AgentState(
        request=request
    )

    # --------------------------------------------------
    # RUN LANGGRAPH
    # --------------------------------------------------

    result = graph.invoke(initial_state)

    # LangGraph may return a dictionary representation
    # of our AgentState.
    final_state = AgentState.model_validate(result)

    # --------------------------------------------------
    # DISPLAY RESULT
    # --------------------------------------------------

    print("\nFINAL STATUS")
    print("-" * 60)
    print(final_state.status)

    print("\nEXTRACTED ENTITIES")
    print("-" * 60)

    if final_state.extracted_entities:
        print(
            final_state.extracted_entities.model_dump_json(
                indent=2
            )
        )

    print("\nDRAFT DETERMINATION")
    print("-" * 60)

    if final_state.draft_answer:
        print(
            final_state.draft_answer.model_dump_json(
                indent=2
            )
        )
    else:
        print("No draft determination.")

    print("\nVERIFICATION")
    print("-" * 60)

    if final_state.verification:
        print(
            final_state.verification.model_dump_json(
                indent=2
            )
        )
    else:
        print("No verification result.")

    print("\nRETRIEVED EVIDENCE")
    print("-" * 60)

    for chunk_id, chunk in final_state.retrieved_chunks.items():

        print(f"\nChunk ID : {chunk_id}")
        print(f"Section  : {chunk.section}")
        print(f"Clause   : {chunk.clause}")
        print(f"Text     : {chunk.text}")

    print("\nEXECUTION COUNTERS")
    print("-" * 60)

    print("Graph steps          :", final_state.steps)
    print("Tool calls           :", final_state.tool_calls)
    print(
        "Verification retries :",
        final_state.verification_retries
    )

    if final_state.escalation:

        print("\nESCALATION")
        print("-" * 60)

        print(
            final_state.escalation.model_dump_json(
                indent=2
            )
        )

    print("\n" + "=" * 60)
    print(
        "\nOutput guardrail:",
        final_state.metadata.get("output_guardrail")
    )

    print(
        "DISCLAIMER: This is a screening opinion, "
        "not an authoritative environmental clearance determination."
    )

    print("=" * 60 + "\n")




if __name__ == "__main__":
    main()