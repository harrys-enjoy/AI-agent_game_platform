// 제안(Proposal) SSE 구독 + 백그라운드 Gmail/Calendar Polling Context.
// `workmate-ui/lib/proposal-notifications.tsx`에서 이식(19번 문서 7단계) — 원본은
// `useWorkmateAuth()`로 OIDC 토큰을 앱 전역에서 읽었지만, 여기서는 App.tsx가 들고
// 있는 `assigneeName`을 그대로 `config.assignee`로 받는다(나머지 6개 화면과 동일한
// 인증 방식, 2026-08-19 — 로컬 전용 프로젝트 서버라 진짜 OIDC 요구를 담당자-이름
// 인증으로 완화했다, `api.ts` 상단 주석 참고). **범위를 하나 좁혔다**: 원본은 이
// Provider를 앱 Shell 최상단에 마운트해 다른 화면에 가 있어도 SSE가 안 끊겼는데,
// 여기서는 `ProposalsDetailPanel`(제안함 탭 자신)에만 마운트한다 — 그래서 제안함
// 탭을 벗어나면(다른 4개 탭·다른 Agent 채팅) SSE 연결도 끊긴다. 오케스트레이터
// Shell 전체에 Provider를 올리는 건 Toast 배치 등 셸 레이아웃 변경이 더 필요해
// 이후 과제로 남긴다.

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError, devCalendarSyncApi, devGmailSyncApi, streamSse, type WorkmateConfig } from "./api";
import { parseSseBlock, shouldToastProposal } from "./format";
import type { TaskProposal } from "./types";

export type ToastItem = { id: string; proposal: TaskProposal };
export type DesktopPermission = NotificationPermission | "unsupported";

const BACKGROUND_SYNC_INTERVAL_MS = 120_000;
const SSE_RECONNECT_BASE_DELAY_MS = 1000;
const SSE_RECONNECT_MAX_DELAY_MS = 30_000;
const TOAST_TTL_MS = 6000;
const LAST_GMAIL_SYNC_STORAGE_KEY = "workmate-ui:last-gmail-sync-at";

type ProposalNotificationsValue = {
  proposals: TaskProposal[];
  connected: boolean;
  connectError: string | null;
  unseenCount: number;
  markAllSeen: () => void;
  removeProposal: (proposalId: string) => void;
  clearProposals: () => void;
  toasts: ToastItem[];
  dismissToast: (id: string) => void;
  desktopPermission: DesktopPermission;
  requestDesktopPermission: () => void;
};

const ProposalNotificationsContext = createContext<ProposalNotificationsValue | null>(null);

function loadLastGmailSyncAt(): string {
  if (typeof window === "undefined") return new Date().toISOString();
  const stored = window.localStorage.getItem(LAST_GMAIL_SYNC_STORAGE_KEY);
  if (stored) return stored;
  const now = new Date().toISOString();
  window.localStorage.setItem(LAST_GMAIL_SYNC_STORAGE_KEY, now);
  return now;
}

function saveLastGmailSyncAt(value: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(LAST_GMAIL_SYNC_STORAGE_KEY, value);
}

export function ProposalNotificationsProvider({ config, children }: { config: WorkmateConfig; children: ReactNode }) {
  const { apiBase, assignee } = config;
  const [proposals, setProposals] = useState<TaskProposal[]>([]);
  const [connected, setConnected] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [seenIds, setSeenIds] = useState<Set<string>>(new Set());
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [desktopPermission, setDesktopPermission] = useState<DesktopPermission>("default");
  const toastTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const notifiedIds = useRef<Set<string>>(new Set());
  const lastGmailSyncAtRef = useRef<string | null>(null);
  if (lastGmailSyncAtRef.current === null) lastGmailSyncAtRef.current = loadLastGmailSyncAt();

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDesktopPermission(typeof window === "undefined" || typeof Notification === "undefined" ? "unsupported" : Notification.permission);
  }, []);

  useEffect(() => {
    if (!assignee) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setConnected(false);
      return;
    }
    const controller = new AbortController();
    let attempt = 0;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    function handleBlock(block: string) {
      const parsed = parseSseBlock(block);
      if (parsed?.event !== "task_proposal") return;
      const proposal = parsed.data as TaskProposal;
      setProposals((prev) => [proposal, ...prev.filter((item) => item.proposal_id !== proposal.proposal_id)]);
      if (!notifiedIds.current.has(proposal.proposal_id)) {
        notifiedIds.current.add(proposal.proposal_id);
        if (shouldToastProposal(proposal, lastGmailSyncAtRef.current)) {
          const toastId = `${proposal.proposal_id}-${Date.now()}`;
          setToasts((prev) => [...prev, { id: toastId, proposal }]);
          const timer = setTimeout(() => dismissToast(toastId), TOAST_TTL_MS);
          toastTimers.current.set(toastId, timer);
          if (typeof window !== "undefined" && typeof Notification !== "undefined" && Notification.permission === "granted") {
            try {
              const notification = new Notification("Workmate — 새 제안 도착", { body: proposal.title, tag: proposal.proposal_id });
              notification.onclick = () => window.focus();
            } catch {
              // Notification API 미지원·차단 환경은 Toast만으로 충분하다.
            }
          }
        }
      }
    }

    function connect() {
      if (controller.signal.aborted) return;
      setConnectError(null);
      streamSse(
        { apiBase, assignee },
        "assignee",
        "/api/v1/notifications/stream",
        handleBlock,
        controller.signal,
        () => {
          attempt = 0;
          setConnected(true);
          setConnectError(null);
        },
      )
        .catch((err) => {
          if (!controller.signal.aborted) setConnectError(err instanceof Error ? err.message : "SSE 연결 오류");
        })
        .finally(() => {
          if (controller.signal.aborted) return;
          setConnected(false);
          const delay = Math.min(SSE_RECONNECT_BASE_DELAY_MS * 2 ** attempt, SSE_RECONNECT_MAX_DELAY_MS);
          attempt += 1;
          retryTimer = setTimeout(connect, delay);
        });
    }

    connect();
    return () => {
      controller.abort();
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [apiBase, assignee]);

  useEffect(() => {
    if (!assignee) return;
    let cancelled = false;

    async function runBackgroundSync() {
      try {
        await devGmailSyncApi.trigger({ apiBase, assignee }, 5);
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 404)) console.warn("background gmail sync failed", err);
      }
      if (cancelled) return;
      try {
        await devCalendarSyncApi.trigger({ apiBase, assignee });
      } catch (err) {
        if (!(err instanceof ApiError && (err.status === 404 || err.status === 403))) console.warn("background calendar sync failed", err);
      }
      if (!cancelled) {
        const now = new Date().toISOString();
        lastGmailSyncAtRef.current = now;
        saveLastGmailSyncAt(now);
      }
    }

    void runBackgroundSync();
    const interval = setInterval(() => void runBackgroundSync(), BACKGROUND_SYNC_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [apiBase, assignee]);

  function dismissToast(id: string) {
    setToasts((prev) => prev.filter((item) => item.id !== id));
    const timer = toastTimers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      toastTimers.current.delete(id);
    }
  }

  function markAllSeen() {
    setSeenIds(new Set(proposals.map((item) => item.proposal_id)));
  }

  function removeProposal(proposalId: string) {
    setProposals((prev) => prev.filter((item) => item.proposal_id !== proposalId));
    setSeenIds((prev) => {
      const next = new Set(prev);
      next.delete(proposalId);
      return next;
    });
    notifiedIds.current.delete(proposalId);
  }

  function clearProposals() {
    setProposals([]);
    setSeenIds(new Set());
    notifiedIds.current.clear();
    toastTimers.current.forEach((timer) => clearTimeout(timer));
    toastTimers.current.clear();
    setToasts([]);
  }

  function requestDesktopPermission() {
    if (typeof Notification === "undefined") return;
    void Notification.requestPermission().then((permission) => setDesktopPermission(permission));
  }

  const unseenCount = proposals.filter((item) => !seenIds.has(item.proposal_id)).length;

  const value: ProposalNotificationsValue = {
    proposals,
    connected,
    connectError,
    unseenCount,
    markAllSeen,
    removeProposal,
    clearProposals,
    toasts,
    dismissToast,
    desktopPermission,
    requestDesktopPermission,
  };

  return <ProposalNotificationsContext.Provider value={value}>{children}</ProposalNotificationsContext.Provider>;
}

export function useProposalNotifications(): ProposalNotificationsValue {
  const value = useContext(ProposalNotificationsContext);
  if (!value) throw new Error("useProposalNotifications must be used within ProposalNotificationsProvider");
  return value;
}
