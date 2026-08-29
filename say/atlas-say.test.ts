import { describe, expect, test } from "bun:test";
import { generateAtlasSpeech, validateAtlasContract } from "./atlas-say";

const model = {
  model: "google/gemini-2.5-flash-tts",
  display_console: true,
  schema: "https://example.test/schema.json",
  price: { actual: { base_price: "0.04" } },
};
const schema = {
  paths: {
    "/api/v1/model/generateAudio": { post: {} },
    "/api/v1/model/prediction/{request_id}": { get: {} },
  },
  components: {
    schemas: {
      Input: {
        properties: {
          model: { enum: [model.model] },
          text: { type: "string" },
          voice: { enum: ["Charon", "Kore"] },
        },
      },
    },
  },
};

describe("Atlas TTS", () => {
  test("accepts only the live console model and schema", async () => {
    const fetcher = async (url: string | URL | Request) => {
      const value = String(url);
      if (value.endsWith("/models")) return Response.json({ code: 200, data: [model] });
      if (value === model.schema) return Response.json(schema);
      return new Response(null, { status: 404 });
    };
    const result = await validateAtlasContract(fetcher as typeof fetch);
    expect(result.price).toBe("0.04");
  });

  test("accepts the catalog's string success code", async () => {
    const fetcher = async (url: string | URL | Request) => {
      const value = String(url);
      if (value.endsWith("/models")) return Response.json({ code: "200", data: [model] });
      if (value === model.schema) return Response.json(schema);
      return new Response(null, { status: 404 });
    };
    await expect(validateAtlasContract(fetcher as typeof fetch)).resolves.toMatchObject({ price: "0.04" });
  });

  test("submits once and bounds prediction GET polling", async () => {
    const methods: string[] = [];
    let polls = 0;
    const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
      const value = String(url);
      const method = init?.method ?? "GET";
      if (value.endsWith("/models")) return Response.json({ code: 200, data: [model] });
      if (value === model.schema) return Response.json(schema);
      methods.push(method);
      if (value.endsWith("/generateAudio")) {
        expect(JSON.parse(String(init?.body))).toEqual({ model: model.model, text: "Hello", voice: "Charon" });
        return Response.json({ code: 200, data: { id: "prediction-1", status: "starting" } });
      }
      if (value.includes("/prediction/")) {
        polls += 1;
        return Response.json({ code: 200, data: polls === 2
          ? { id: "prediction-1", status: "completed", outputs: ["https://example.test/audio.wav"] }
          : { id: "prediction-1", status: "processing" } });
      }
      return new Response(null, { status: 404 });
    };
    const delays: number[] = [];
    const result = await generateAtlasSpeech("Hello", "Charon", "test-key", {
      fetcher: fetcher as typeof fetch,
      sleep: async (milliseconds) => { delays.push(milliseconds); },
      maxPolls: 3,
    });
    expect(result.outputUrl).toBe("https://example.test/audio.wav");
    expect(methods.filter((method) => method === "POST")).toHaveLength(1);
    expect(methods.filter((method) => method === "GET")).toHaveLength(2);
    expect(delays).toEqual([1_000]);
  });

  test("rejects a voice absent from the live schema before submission", async () => {
    let submitted = false;
    const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
      const value = String(url);
      if (value.endsWith("/models")) return Response.json({ code: 200, data: [model] });
      if (value === model.schema) return Response.json(schema);
      if (init?.method === "POST") submitted = true;
      return new Response(null, { status: 404 });
    };
    await expect(generateAtlasSpeech("Hello", "Unknown", "test-key", { fetcher: fetcher as typeof fetch }))
      .rejects.toThrow("not supported");
    expect(submitted).toBe(false);
  });

  test("stops immediately when the prediction fails", async () => {
    let polls = 0;
    const fetcher = async (url: string | URL | Request) => {
      const value = String(url);
      if (value.endsWith("/models")) return Response.json({ code: 200, data: [model] });
      if (value === model.schema) return Response.json(schema);
      if (value.endsWith("/generateAudio")) return Response.json({ code: 200, data: { id: "prediction-2" } });
      if (value.includes("/prediction/")) {
        polls += 1;
        return Response.json({ code: 200, data: { id: "prediction-2", status: "failed" } });
      }
      return new Response(null, { status: 404 });
    };
    await expect(generateAtlasSpeech("Hello", "Charon", "test-key", {
      fetcher: fetcher as typeof fetch,
      sleep: async () => {},
      maxPolls: 3,
    })).rejects.toThrow("prediction failed");
    expect(polls).toBe(1);
  });
});
