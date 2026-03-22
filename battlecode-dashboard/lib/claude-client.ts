import Anthropic from "@anthropic-ai/sdk";
import type { MatchMetrics } from "@/types/game";

export const ANALYSIS_MODEL = "claude-sonnet-4-20250514";

/** Game rules + analyst behavior (Cambridge Battlecode). */
export const GAME_RULES_SYSTEM_PROMPT = `You are an expert Cambridge Battlecode analyst. You are given pre-computed metrics from a match replay. Your job is to provide actionable strategic analysis.

## Core Mechanics
- 2-player game on a 20×20 to 50×50 grid, symmetric (rotation or reflection)
- Each team has one Core (3×3, 500 HP). If your core dies, you lose.
- Game lasts max 2000 rounds. Tiebreaker: axionite delivered > titanium delivered > harvesters alive > stored resources > coinflip.
- Each team starts with 1000 titanium, 0 axionite.

## Units
- Core: 3×3 building, spawns 1 builder bot/round, vision r²=36, action r²=8
- Builder Bot: only mobile unit, 30 HP, 10 Ti cost, 10% scaling. Can build, heal, destroy allied buildings, self-destruct (20 dmg to tile). Can only walk on conveyors, roads, allied core. Vision r²=20, action r²=2.
- Gunner: 40 HP, 10 Ti, 10% scaling. Shoots closest non-empty tile in facing direction. 10 dmg (20 with refined axionite). 1 round reload, 2 ammo/shot. Vision/attack r²=13.
- Sentinel: 30 HP, 15 Ti, 10% scaling. Hits tiles within 1 king-move of facing line. 20 dmg, 4 round reload, 10 ammo/shot. With refined axionite: +3 cooldown stun. Vision/attack r²=32.
- Breach: 60 HP, 30 Ti + 10 Ax, 10% scaling. 180° cone, 40 direct + 20 splash (friendly fire!). 1 round reload, 5 refined axionite/shot. Vision r²=10, attack r²=5.
- Launcher: 30 HP, 20 Ti, 10% scaling. Throws adjacent builder bots to target tile within r²=26. No ammo. 1 round reload.

## Buildings
- Conveyor: 20 HP, 3 Ti, 1% scaling. Cardinal direction. 3 inputs, 1 output. Holds 1 stack.
- Splitter: 20 HP, 6 Ti, 1%. 1 input (back), 3 rotating outputs.
- Bridge: 20 HP, 10 Ti, 1%. Outputs to specific tile within dist²≤9.
- Armoured Conveyor: 50 HP, 10 Ti + 5 Ax, 1%. Tougher conveyor.
- Harvester: 30 HP, 80 Ti, 10%. Must be on ore. Outputs 1 stack every 4 rounds (first output immediate).
- Foundry: 50 HP, 120 Ti, 100% scaling. Ti + raw axionite → refined axionite.
- Road: 10 HP, 1 Ti, 0.5%. Walkable.
- Barrier: 30 HP, 3 Ti, 1%. Blocks space.
- Marker: 1 HP, free. Stores u32 value. Only comms between units.

## Resources
- Titanium: primary resource, mined from Ti ore.
- Raw Axionite: mined from Ax ore. Decays to Ti if fed to turret/core.
- Refined Axionite: made in foundries from Ti + raw Ax. Powers breach turrets, doubles gunner damage, enables sentinel stun.
- Resources move in stacks of 10 via conveyors.
- Resources delivered to core enter the global pool for building.
- Resources can leak to enemy buildings if conveyors point wrong.

## Cost Scaling
Every build increases a global multiplier: cost = floor(scale × base_cost). Scale starts at 1.0x.
- Road: +0.5%, Conveyors/barriers: +1%, Builder/harvester/turrets: +10%, Foundry: +100%.
- Destroying an entity removes its scaling contribution.

## Analysis rules
- Be specific. Say "Team A built their first harvester at round 45, which is late — aim for round 8-15" not "Team A was slow to build harvesters."
- Reference numbers. Say "With a 78% core hit rate (18/23 self-destructs)" not "good hit rate."
- Be opinionated. Say "This was a mistake" not "This could potentially be suboptimal."
- Suggest concrete counter-strategies with specific build orders and timings.
- Identify the single most impactful decision in the match.
- If a team built turrets that never fired, call that out explicitly.
- If a team built harvesters with no conveyor chains, call that out.
- If scaling went above 300% before round 500, flag it as a problem.
- Compare both teams' economy curves and explain who had the advantage and when.

Structure your answer with these sections (markdown headings):
## Match Summary
## Team A Strategy
## Team B Strategy
## Key Turning Points
## Mistakes & Missed Opportunities
## Economy Analysis
## Combat Efficiency
## What Would Win Against This Opponent
`;

export function getAnthropicClient(): Anthropic {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    throw new Error("ANTHROPIC_API_KEY is not set");
  }
  return new Anthropic({ apiKey });
}

/**
 * Downsample a numeric array to at most `n` evenly-spaced samples.
 * Keeps first and last values for accuracy at boundaries.
 */
function downsample(arr: number[], n: number): number[] {
  if (arr.length <= n) return arr;
  const out: number[] = [arr[0]];
  const step = (arr.length - 1) / (n - 1);
  for (let i = 1; i < n - 1; i++) {
    out.push(arr[Math.round(i * step)]);
  }
  out.push(arr[arr.length - 1]);
  return out;
}

/**
 * Produce a compact version of MatchMetrics that fits comfortably within
 * Claude's context window. Drops heatmaps, per-round distance arrays,
 * downsamples curves to ~50 points, and trims building lists to type+round.
 */
function compactMetrics(m: MatchMetrics): Record<string, unknown> {
  const CURVE_POINTS = 50;
  const compactTeam = (t: MatchMetrics["teams"][string]) => ({
    titanium_curve: downsample(t.titanium_curve, CURVE_POINTS),
    axionite_curve: downsample(t.axionite_curve, CURVE_POINTS),
    scale_curve: downsample(t.scale_curve, CURVE_POINTS),
    total_titanium_spent: t.total_titanium_spent,
    total_axionite_spent: t.total_axionite_spent,
    peak_titanium: t.peak_titanium,
    peak_axionite: t.peak_axionite,
    final_scale: t.final_scale,
    buildings_built_summary: Object.entries(
      t.buildings_built.reduce<Record<string, { count: number; first: number; last: number }>>(
        (acc, b) => {
          if (!acc[b.type]) acc[b.type] = { count: 0, first: b.round, last: b.round };
          acc[b.type].count++;
          acc[b.type].first = Math.min(acc[b.type].first, b.round);
          acc[b.type].last = Math.max(acc[b.type].last, b.round);
          return acc;
        },
        {},
      ),
    ).map(([type, v]) => ({ type, ...v })),
    first_harvester_round: t.first_harvester_round,
    first_gunner_round: t.first_gunner_round,
    first_launcher_round: t.first_launcher_round,
    first_foundry_round: t.first_foundry_round,
    total_harvesters_built: t.total_harvesters_built,
    total_gunners_built: t.total_gunners_built,
    total_conveyors_built: t.total_conveyors_built,
    total_roads_built: t.total_roads_built,
    total_barriers_built: t.total_barriers_built,
    total_builders_spawned: t.total_builders_spawned,
    peak_builder_count: t.peak_builder_count,
    builder_spawn_rate: t.builder_spawn_rate,
    total_self_destructs: t.total_self_destructs,
    core_hits: t.core_hits,
    core_damage_dealt: t.core_damage_dealt,
    turret_shots_fired: t.turret_shots_fired,
    turret_damage_dealt: t.turret_damage_dealt,
    self_destruct_efficiency: t.self_destruct_efficiency,
    harvesters_with_connected_chain: t.harvesters_with_connected_chain,
    harvesters_without_chain: t.harvesters_without_chain,
    turrets_that_fired: t.turrets_that_fired,
    turrets_that_never_fired: t.turrets_that_never_fired,
  });

  return {
    winner: m.winner,
    win_reason: m.win_reason,
    total_rounds: m.total_rounds,
    map_size: m.map_size,
    teams: {
      a: compactTeam(m.teams.a),
      b: compactTeam(m.teams.b),
    },
    core_a_hp_curve: downsample(m.core_a_hp_curve, CURVE_POINTS),
    core_b_hp_curve: downsample(m.core_b_hp_curve, CURVE_POINTS),
    first_blood_round: m.first_blood_round,
    first_blood_team: m.first_blood_team,
  };
}

export async function analyzeMatchStream(metrics: MatchMetrics): Promise<ReadableStream<Uint8Array>> {
  const client = getAnthropicClient();
  const compact = compactMetrics(metrics);

  const stream = await client.messages.create({
    model: ANALYSIS_MODEL,
    max_tokens: 4000,
    stream: true,
    system: GAME_RULES_SYSTEM_PROMPT,
    messages: [
      {
        role: "user",
        content: `Analyze this Cambridge Battlecode match. Here are the pre-computed metrics (curves are downsampled to ~50 evenly-spaced data points):

${JSON.stringify(compact, null, 2)}

Provide a thorough strategic analysis covering: match summary, each team's strategy, key turning points, mistakes, economy analysis, combat efficiency, and counter-strategy recommendations. Be specific — reference exact round numbers, building counts, and percentages. Be opinionated about what was good and bad.`,
      },
    ],
  });

  const enc = new TextEncoder();

  return new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        for await (const event of stream) {
          if (
            event.type === "content_block_delta" &&
            event.delta.type === "text_delta" &&
            event.delta.text
          ) {
            controller.enqueue(
              enc.encode(`data: ${JSON.stringify({ text: event.delta.text })}\n\n`),
            );
          }
        }
        controller.enqueue(enc.encode("data: [DONE]\n\n"));
        controller.close();
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Analysis failed";
        controller.enqueue(
          enc.encode(`data: ${JSON.stringify({ error: msg })}\n\n`),
        );
        controller.close();
      }
    },
  });
}
