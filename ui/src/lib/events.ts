// Mirrors engine/src/paddock/bus/events.py — keep field names in sync,
// this is the wire contract for /events and the demo stream.

export type WorkerState = "idle" | "busy" | "error";
export type OrderSide = "back" | "lay";
export type LogLevel = "debug" | "info" | "warning" | "error";

interface BaseEvent {
  event_id: string;
  ts_ms: number;
}

export interface WorkerHeartbeat extends BaseEvent {
  type: "worker.heartbeat";
  name: string;
  state: WorkerState;
  last_latency_ms: number | null;
}

export interface Runner {
  selection_id: number;
  name: string | null;
}

export interface MarketOpen extends BaseEvent {
  type: "market.open";
  market_id: string;
  venue: string | null;
  race_name: string | null;
  off_time: string | null;
  runners: Runner[];
}

export interface MarketClose extends BaseEvent {
  type: "market.close";
  market_id: string;
}

export interface PriceLevel {
  price: number;
  size: number;
}

export interface RunnerPrice extends BaseEvent {
  type: "runner.price";
  market_id: string;
  selection_id: number;
  back: PriceLevel[];
  lay: PriceLevel[];
  ltp: number | null;
  traded_volume: number | null;
}

export interface StrategySignal extends BaseEvent {
  type: "strategy.signal";
  strategy: string;
  market_id: string;
  selection_id: number;
  reason: string;
  confidence: number | null;
}

export interface OrderEvent extends BaseEvent {
  type: "order.placed" | "order.matched" | "order.cancelled" | "order.lapsed";
  order_id: string;
  market_id: string;
  selection_id: number;
  side: OrderSide;
  price: number;
  size: number;
  matched_size: number;
}

export interface PnlUpdate extends BaseEvent {
  type: "pnl.update";
  run_id: string;
  market_id: string | null;
  market_pnl: number | null;
  run_pnl: number;
  commission: number;
  // "ltp_cross" numbers are an optimistic upper bound, not a backtest
  // result — see engine/src/paddock/sim/fill_models.py.
  fill_model: string;
}

export interface RunConfig extends BaseEvent {
  type: "run.config";
  run_id: string;
  mode: string;
  fill_model: string;
  commission_rate: number;
}

export interface LogEvent extends BaseEvent {
  type: "log";
  level: LogLevel;
  msg: string;
}

export type PaddockEvent =
  | WorkerHeartbeat
  | MarketOpen
  | MarketClose
  | RunnerPrice
  | StrategySignal
  | OrderEvent
  | PnlUpdate
  | RunConfig
  | LogEvent;

export interface Snapshot {
  type: "snapshot";
  data: {
    workers: WorkerHeartbeat[];
    markets: MarketOpen[];
    pnl: PnlUpdate | null;
    run_config: RunConfig | null;
  };
}

export type WireMessage = Snapshot | PaddockEvent;

// Particle-flow edges the Floor scene animates events along, keyed by event type.
export const FLOOR_EDGES: Record<string, [string, string] | undefined> = {
  "runner.price": ["stream", "strategy"],
  "strategy.signal": ["strategy", "executor"],
  "order.placed": ["executor", "executor"],
  "order.matched": ["executor", "pnl"],
  "order.cancelled": ["executor", "executor"],
  "order.lapsed": ["executor", "executor"],
};
