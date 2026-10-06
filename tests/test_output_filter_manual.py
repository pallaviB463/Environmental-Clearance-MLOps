from agent.guardrails.output_filter import validate_output


print("\n=== TEST 1: SAFE OUTPUT ===")

safe_result = validate_output(
    text=(
        "The screening indicates Category A "
        "with central routing."
    ),
    route="category_a_central"
)

print(safe_result)


print("\n=== TEST 2: UNSAFE CLAIM ===")

unsafe_result = validate_output(
    text=(
        "Environmental clearance is granted "
        "for this project."
    ),
    route="category_a_central"
)

print(unsafe_result)


print("\n=== TEST 3: INVALID ROUTE ===")

invalid_route_result = validate_output(
    text="Screening completed.",
    route="automatic_approval"
)

print(invalid_route_result)