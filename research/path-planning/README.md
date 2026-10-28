# Communication-Aware Path Planning

Future goal: compare robot routes using travel cost, task constraints, safety, and predicted communication quality.

## Expected evaluation

- State robot motion and obstacle assumptions explicitly.
- Define a communication objective (for example, minimum expected packet-delivery probability or a penalty for poor link quality).
- Compare against shortest-path and other simple baselines.
- Keep safety and collision avoidance hard constraints rather than trading them away for signal quality.
- Evaluate across independent maps or sessions and report distance, completion rate, communication metrics, and computation cost.
- Treat prediction uncertainty and uncovered regions conservatively.

Planning integration is not considered implemented until validated in simulation and then tested under controlled field conditions.