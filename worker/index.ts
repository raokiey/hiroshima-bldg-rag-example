import { Container } from "@cloudflare/containers";
import { env } from "cloudflare:workers";

/**
 * Wraps the FastAPI backend (see ../Dockerfile) as a Cloudflare Container.
 *
 * One instance serves all traffic — this is a single-tenant demo app, not a
 * multi-user service, so there is no need to spin up a container per user.
 */
export class HiroshimaBuildingRagContainer extends Container {
  defaultPort = 8000;

  // Sleep after inactivity to save cost between demo sessions. The FastAPI
  // app's lifespan hook re-prewarms the RURI model (~15-20s) on cold start,
  // so a wake-up after sleep is a brief but noticeable delay, not a failure.
  sleepAfter = "10m";

  envVars = {
    GEMINI_API_KEY: env.GEMINI_API_KEY,
  };
}

interface Env {
  HIROSHIMA_CONTAINER: DurableObjectNamespace<HiroshimaBuildingRagContainer>;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    // Fixed instance name ("default") so every request is routed to the same
    // single container instance rather than spawning one per caller.
    const container = env.HIROSHIMA_CONTAINER.getByName("default");
    return container.fetch(request);
  },
} satisfies ExportedHandler<Env>;
