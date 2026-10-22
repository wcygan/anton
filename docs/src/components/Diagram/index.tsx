import {NodeShape, type DiagramShape, type Bounds} from './shapes';
export {nodeShapes, type DiagramShape} from './shapes';

import React, {createContext, useContext, useId, type ReactNode} from 'react';

export type DiagramRole = 'processing' | 'storage' | 'flow' | 'control';
const ArrowId = createContext<string | null>(null);

type DiagramProps = {
  title: string;
  description: string;
  width: number;
  height: number;
  children: ReactNode;
};

export function Diagram({title, description, width, height, children}: DiagramProps) {
  const id = useId().replace(/:/g, '');
  const arrowId = `${id}-arrow`;
  return (
    <div className="diagram-panel">
      <svg className="diagram-svg" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby={`${id}-title ${id}-description`}>
        <title id={`${id}-title`}>{title}</title>
        <desc id={`${id}-description`}>{description}</desc>
        <defs>
          <marker id={arrowId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" className="diagram-arrowhead" />
          </marker>
        </defs>
        <ArrowId.Provider value={arrowId}>{children}</ArrowId.Provider>
      </svg>
    </div>
  );
}

type NodeProps = Bounds & {label: string | readonly string[]; role: DiagramRole; shape?: DiagramShape};

export function DiagramNode({x, y, width, height, label, role, shape = 'box'}: NodeProps) {
  const lines = typeof label === 'string' ? [label] : label;
  const centerX = x + width / 2 + (shape === 'volume' ? 14 : shape === 'replicas' ? -5 : 0);
  const centerY = y + height / 2 + (shape === 'client' ? -6 : shape === 'server' ? -4.5 : shape === 'replicas' ? 5 : shape === 'bucket' || shape === 'storage' ? 4 : 0);
  const top = centerY - (lines.length - 1) * 9.5 + 5;
  return (
    <g className={`diagram-node ${role}`} data-shape={shape}>
      <NodeShape shape={shape} x={x} y={y} width={width} height={height} />
      <text x={centerX} textAnchor="middle">
        {lines.map((line, index) => <tspan key={index} x={centerX} y={top + index * 19}>{line}</tspan>)}
      </text>
    </g>
  );
}

export function DiagramGroup({x, y, width, height, label, labelAlign = 'middle', variant = 'solid'}: Bounds & {label: string; labelAlign?: 'start' | 'middle'; variant?: 'solid' | 'dashed'}) {
  return <>
    <rect className={`diagram-group diagram-group-${variant}`} x={x} y={y} width={width} height={height} rx="10" />
    <text className="diagram-heading" x={labelAlign === 'start' ? x + 14 : x + width / 2} y={y + 27} textAnchor={labelAlign}>{label}</text>
  </>;
}

export function DiagramArrow({d}: {d: string}) {
  const id = useContext(ArrowId);
  if (!id) throw new Error('DiagramArrow must be inside Diagram');
  return <path d={d} className="diagram-connector" markerEnd={`url(#${id})`} />;
}
