import React from 'react';

export const nodeShapes = ['box', 'storage', 'server', 'bucket', 'document', 'client', 'decision', 'volume', 'gateway', 'replicas'] as const;
export type DiagramShape = typeof nodeShapes[number];
export type Bounds = {x: number; y: number; width: number; height: number};

export function NodeShape({shape, x, y, width: w, height: h}: Bounds & {shape: DiagramShape}) {
  const cap = Math.min(12, h / 5);
  const diskSize = Math.min(56, h - 8, w * .33);
  const fold = Math.min(16, w / 6, h / 3);
  const box = <rect className="diagram-shape" x={x} y={y} width={w} height={h} rx="6" />;
  switch (shape) {
    case 'box': return box;
    case 'storage': return <>
      <path className="diagram-shape" d={`M ${x} ${y + cap} a ${w / 2} ${cap} 0 0 1 ${w} 0 v ${h - 2 * cap} a ${w / 2} ${cap} 0 0 1 ${-w} 0 Z`} />
      <ellipse className="diagram-shape" cx={x + w / 2} cy={y + cap} rx={w / 2} ry={cap} />
    </>;
    case 'server': return <>
      {box}
      <path className="diagram-detail" d={`M ${x} ${y + h - 9} H ${x + w}`} />
      <circle className="diagram-detail" cx={x + 10} cy={y + h - 4.5} r="1.5" />
      <path className="diagram-detail" d={`M ${x + w - 26} ${y + h - 4.5} h 16`} />
    </>;
    case 'bucket': return <>
      <path className="diagram-shape" d={`M ${x} ${y + cap} L ${x + w * .12} ${y + h - cap} Q ${x + w / 2} ${y + h + cap} ${x + w * .88} ${y + h - cap} L ${x + w} ${y + cap} Z`} />
      <ellipse className="diagram-shape" cx={x + w / 2} cy={y + cap} rx={w / 2} ry={cap} />
    </>;
    case 'document': return <>
      <path className="diagram-shape" d={`M ${x} ${y} H ${x + w - fold} L ${x + w} ${y + fold} V ${y + h} H ${x} Z`} />
      <path className="diagram-detail" d={`M ${x + w - fold} ${y} V ${y + fold} H ${x + w}`} />
    </>;
    case 'client': return <>
      <rect className="diagram-shape" x={x} y={y} width={w} height={h - 12} rx="5" />
      <path className="diagram-connector" d={`M ${x + w / 2} ${y + h - 12} v 12 M ${x + w * .3} ${y + h} H ${x + w * .7}`} />
    </>;
    case 'decision': return <path className="diagram-shape" d={`M ${x + w / 2} ${y} L ${x + w} ${y + h / 2} L ${x + w / 2} ${y + h} L ${x} ${y + h / 2} Z`} />;
    case 'volume': return <>
      {box}
      <svg x={x + 2} y={y + (h - diskSize) / 2} width={diskSize} height={diskSize} viewBox="0 0 512 512" className="diagram-drive-icon" aria-hidden="true">
        <path className="diagram-drive-base" d="M 96 256 H 416 V 464 Q 416 496 384 496 H 128 Q 96 496 96 464 Z" />
        <rect className="diagram-drive-case" x="96" y="16" width="320" height="448" rx="24" />
        <path className="diagram-drive-plate" d="M 96 272 L 224 400 H 244 L 308 464 H 128 Q 96 464 96 432 Z" />
        <path className="diagram-drive-line" d="M 96 256 L 160 320 M 244 400 L 308 464" />
        <circle className="diagram-drive-platter" cx="256" cy="176" r="144" />
        <circle className="diagram-drive-hub" cx="256" cy="176" r="40" />
        <g className="diagram-drive-ink">
          <circle cx="256" cy="160" r="8" /><circle cx="240" cy="176" r="8" />
          <circle cx="272" cy="176" r="8" /><circle cx="256" cy="192" r="8" />
        </g>
        <path className="diagram-drive-arm" d="M 291 268 L 163 350 C 145 362 140 382 152 399 C 165 419 193 422 210 403 Z" />
        <g className="diagram-drive-ink"><circle cx="184" cy="376" r="8" /><circle cx="120" cy="440" r="8" /></g>
      </svg>
    </>;
    case 'gateway': return <>
      {box}
      <path className="diagram-detail" d={`M ${x + 12} ${y} V ${y + h} M ${x + w - 12} ${y} V ${y + h}`} />
    </>;
    case 'replicas': return <>
      <rect className="diagram-shape" x={x + 10} y={y} width={w - 10} height={h - 10} rx="5" />
      <rect className="diagram-shape" x={x + 5} y={y + 5} width={w - 10} height={h - 10} rx="5" />
      <rect className="diagram-shape" x={x} y={y + 10} width={w - 10} height={h - 10} rx="5" />
    </>;
  }
}
