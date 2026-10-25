// 残差/Cd 实时曲线（对数残差 + 线性 Cd 双轴，纯 canvas，无第三方依赖）

export interface ChartPoint {
  iter: number;
  u: number;
  p: number;
  cd: number | null;
}

export class ResidualChart {
  private ctx: CanvasRenderingContext2D;
  private points: ChartPoint[] = [];

  constructor(private canvas: HTMLCanvasElement) {
    this.ctx = canvas.getContext("2d")!;
  }

  push(p: ChartPoint) {
    this.points.push(p);
    if (this.points.length > 5000) this.points.splice(0, 1000); // 防内存膨胀
    this.draw();
  }

  reset() {
    this.points = [];
    this.draw();
  }

  draw() {
    const { canvas, ctx, points } = this;
    const w = (canvas.width = canvas.clientWidth * devicePixelRatio);
    const h = (canvas.height = canvas.clientHeight * devicePixelRatio);
    ctx.clearRect(0, 0, w, h);
    if (points.length < 2) return;

    const pad = 40 * devicePixelRatio;
    const iters = points.map((p) => p.iter);
    const i0 = Math.min(...iters);
    const i1 = Math.max(...iters, i0 + 1);
    const resVals = points
      .flatMap((p) => [p.u, p.p])
      .filter((v) => v > 0 && Number.isFinite(v));
    const resMin = Math.max(1e-8, Math.min(...resVals, 1e-3));
    const resMax = Math.max(...resVals, 1);
    const cdVals = points.map((p) => p.cd).filter((v): v is number => v != null);
    const cdMin = cdVals.length ? Math.min(...cdVals) : 0;
    const cdMax = cdVals.length ? Math.max(...cdVals, cdMin + 0.1) : 1;

    const x = (it: number) => pad + ((it - i0) / (i1 - i0)) * (w - pad);
    const yRes = (v: number) =>
      h - pad - ((Math.log10(Math.max(v, resMin)) - Math.log10(resMin)) /
        (Math.log10(resMax) - Math.log10(resMin) || 1)) * (h - 2 * pad);
    const yCd = (v: number) =>
      h - pad - ((v - cdMin) / (cdMax - cdMin || 1)) * (h - 2 * pad);

    // 残差（对数轴）
    drawSeries(ctx, points, x, yRes, (p) => p.u, "#4fc3f7");
    drawSeries(ctx, points, x, yRes, (p) => p.p, "#ffb74d");
    drawSeries(ctx, points, x, yCd, (p) => p.cd, "#81c784");

    ctx.font = `${12 * devicePixelRatio}px sans-serif`;
    ctx.fillStyle = "#4fc3f7";
    ctx.fillText("U 残差", pad, 14 * devicePixelRatio);
    ctx.fillStyle = "#ffb74d";
    ctx.fillText("p 残差", pad + 70 * devicePixelRatio, 14 * devicePixelRatio);
    ctx.fillStyle = "#81c784";
    ctx.fillText("Cd", pad + 140 * devicePixelRatio, 14 * devicePixelRatio);
  }
}

function drawSeries(
  ctx: CanvasRenderingContext2D,
  points: ChartPoint[],
  x: (it: number) => number,
  y: (v: number) => number,
  get: (p: ChartPoint) => number | null,
  color: string
) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5 * devicePixelRatio;
  ctx.beginPath();
  let started = false;
  for (const p of points) {
    const v = get(p);
    if (v == null || !Number.isFinite(v)) continue;
    const px = x(p.iter);
    const py = y(v);
    if (!started) {
      ctx.moveTo(px, py);
      started = true;
    } else {
      ctx.lineTo(px, py);
    }
  }
  ctx.stroke();
}
