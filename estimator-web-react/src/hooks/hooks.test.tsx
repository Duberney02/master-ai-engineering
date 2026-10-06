import { act, renderHook, waitFor } from "@testing-library/react";
import { useElapsedSeconds } from "./useElapsedSeconds";
import { usePromptPreview } from "./usePromptPreview";

describe("useElapsedSeconds", () => {
  afterEach(() => vi.useRealTimers());

  test("cuenta segundos mientras corre y vuelve a 0 al reiniciar", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ running }) => useElapsedSeconds(running), {
      initialProps: { running: false },
    });
    expect(result.current).toBe(0);

    rerender({ running: true });
    act(() => vi.advanceTimersByTime(3000));
    expect(result.current).toBe(3);

    rerender({ running: false });
    act(() => vi.advanceTimersByTime(5000));
    expect(result.current).toBe(3);

    rerender({ running: true });
    expect(result.current).toBe(0);
  });
});

const fetchMock = vi.fn();

function preview(prompt: string) {
  return new Response(JSON.stringify({ system_prompt: prompt, examples: [] }), { status: 200 });
}

describe("usePromptPreview", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  const base = { prompt_version: "v3", project_type: "web_saas", detail_level: "medium", output_format: "phases_table" };

  test("carga el prompt de las opciones vigentes", async () => {
    fetchMock.mockResolvedValue(preview("prompt A"));
    const { result } = renderHook(() => usePromptPreview(base));
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.preview?.system_prompt).toBe("prompt A"));
    expect(result.current.loading).toBe(false);
  });

  test("al cambiar las opciones pide el nuevo prompt e ignora la respuesta obsoleta", async () => {
    let resolveFirst: (value: Response) => void = () => {};
    fetchMock
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { resolveFirst = resolve; }))
      .mockResolvedValueOnce(preview("prompt B"));

    const { result, rerender } = renderHook(({ options }) => usePromptPreview(options), {
      initialProps: { options: base },
    });
    rerender({ options: { ...base, detail_level: "detailed" } });
    await waitFor(() => expect(result.current.preview?.system_prompt).toBe("prompt B"));

    await act(async () => resolveFirst(preview("prompt obsoleto")));
    expect(result.current.preview?.system_prompt).toBe("prompt B");
    expect(fetchMock.mock.calls[1][0]).toContain("detail_level=detailed");
  });

  test("si la API falla devuelve null sin lanzar", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 500 }));
    const { result } = renderHook(() => usePromptPreview(base));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.preview).toBeNull();
  });

  test("sin opciones no llama a la API", () => {
    const { result } = renderHook(() => usePromptPreview(null));
    expect(result.current).toEqual({ preview: null, loading: false });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
