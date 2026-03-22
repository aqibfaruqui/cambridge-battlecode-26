"use client";

interface RoundSliderProps {
  min: number;
  max: number;
  value: number;
  onChange: (v: number) => void;
  label: string;
}

export function RoundSlider({ min, max, value, onChange, label }: RoundSliderProps) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1 font-mono text-[11px]">
      <div className="flex justify-between text-[#8a8a9a]">
        <span>{label}</span>
        <span className="text-[#c8c8d8]">
          {value} / {max}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-1.5 w-full cursor-pointer accent-[#4fc3f7]"
      />
    </div>
  );
}
