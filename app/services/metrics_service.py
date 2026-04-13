from collections import Counter, defaultdict


class MetricsService:
    def __init__(self) -> None:
        self.counters = Counter()
        self.histograms = defaultdict(list)

    def record_request(self, *, success: bool) -> None:
        self.counters["requests_total"] += 1
        if success:
            self.counters["requests_success"] += 1

    def record_run(
        self,
        *,
        run_type: str,
        model_name: str | None,
        latency_ms: int | None,
        cost_usd: float | None,
        cache_resolution: str | None,
    ) -> None:
        self.counters[f"runs_total:{run_type}"] += 1
        if model_name:
            self.counters[f"runs_by_model:{model_name}"] += 1
        if cache_resolution:
            self.counters[f"cache_resolution:{cache_resolution}"] += 1
        if latency_ms is not None:
            self.histograms[f"latency:{run_type}"].append(latency_ms)
        if cost_usd is not None:
            self.histograms[f"cost:{run_type}"].append(cost_usd)

    def snapshot(self) -> dict:
        return {
            "counters": dict(self.counters),
            "histograms": {key: values[:] for key, values in self.histograms.items()},
        }
