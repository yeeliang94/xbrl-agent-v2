import { useCallback, useEffect, useState } from "react";
import { api, errorMessage, type Reports, type RunEvent } from "../../api";

export interface ReportsData {
  data: Reports | null;
  error: string;
  reload: () => Promise<void>;
}

/** The run's three reports. Each reports-agent event reads them again, so saved fields appear as they land. */
export function useReports(runId: number, events: RunEvent[]): ReportsData {
  const [data, setData] = useState<Reports | null>(null);
  const [error, setError] = useState("");
  const seen = events.filter((e) => e.source === "reports").length;

  const reload = useCallback(async () => {
    try {
      setData(await api.reports(runId));
      setError("");
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }, [runId]);

  useEffect(() => {
    void reload();
  }, [reload, seen]);

  return { data, error, reload };
}
