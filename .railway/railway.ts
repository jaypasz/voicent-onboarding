import { defineRailway, github, project, service } from "railway/iac";
// This repository manages only its own resources in the environment. Other
// repositories export their own partial name.
// See https://docs.railway.com/infrastructure-as-code#multi-repo-projects
export const partial = "voicent-onboarding";
export default defineRailway(() => {
  const voicentOnboarding = service("voicent-onboarding", {
    source: github("jaypasz/voicent-onboarding", { branch: "main", checkSuites: false }),
    build: { buildEnvironment: "V3", builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
    start: "",
    healthcheck: "/api/health",
    healthcheckTimeout: 120,
    preDeploy: "alembic upgrade head",
    replicas: { "us-east4-eqdc4a": 1 },
    // Kept from railway.json: restart a crashed container, at most 5 times.
    deploy: { restartPolicyType: "ON_FAILURE", restartPolicyMaxRetries: 5 },
  });

  return project("unique-commitment", {
    variables: { managed: false },
    resources: [voicentOnboarding],
  });
});
