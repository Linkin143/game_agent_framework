from orchestrator.graph import GameOrchestrator

# build dependencies
orchestrator = GameOrchestrator(
    perception_agent=perception_agent,
    decision_agent=decision_agent,
    action_agent=action_agent,
    verification_agent=verification_agent,
    memory_agent=memory_agent,
    executor=executor,
)

result = orchestrator.run(
    goal="Launch Bloons TD6 and reach gameplay",
    app_package="com.netflix.NGP.BloonsTDSix"
)

print(result)