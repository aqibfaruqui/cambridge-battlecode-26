/** Canonical replay shape used by the dashboard after parsing / mock generation */

export type TeamId = "a" | "b";

export type TileType =
  | "empty"
  | "wall"
  | "ore_titanium"
  | "ore_axionite";

export interface ReplayMap {
  width: number;
  height: number;
  tiles: TileType[][];
}

export interface ParsedEntity {
  id: number;
  type: string;
  position: [number, number];
  hp: number;
  team: TeamId;
  direction?: string;
  stored_resource?: string | null;
  ammo?: number;
  /** For core: width/height in tiles (anchor = top-left of footprint) */
  footprint_w?: number;
  footprint_h?: number;
}

export interface TeamState {
  titanium: number;
  axionite: number;
  scale_percent: number;
  entities: ParsedEntity[];
}

export type GameEventType =
  | "spawn"
  | "move"
  | "build"
  | "destroy"
  | "fire"
  | "launch"
  | "self_destruct"
  | "heal"
  | "resource_transfer"
  | "damage";

export interface GameEvent {
  type: GameEventType;
  round: number;
  team: TeamId;
  entity_id?: number;
  position?: [number, number];
  target?: [number, number];
  building_type?: string;
  damage?: number;
  resource_type?: string;
}

export interface RoundSnapshot {
  round_number: number;
  team_a: TeamState;
  team_b: TeamState;
  events: GameEvent[];
}

export interface ParsedReplay {
  map: ReplayMap;
  rounds: RoundSnapshot[];
  winner: TeamId | null;
  win_reason: string;
  /** Original JSON for Raw Data tab */
  raw: unknown;
}

export interface MatchMetrics {
  winner: TeamId | null;
  win_reason: string;
  total_rounds: number;
  map_size: [number, number];
  teams: Record<
    string,
    {
      titanium_curve: number[];
      axionite_curve: number[];
      scale_curve: number[];
      total_titanium_spent: number;
      total_axionite_spent: number;
      peak_titanium: number;
      peak_axionite: number;
      final_scale: number;
      buildings_built: {
        type: string;
        round: number;
        position: [number, number];
      }[];
      first_harvester_round: number | null;
      first_gunner_round: number | null;
      first_launcher_round: number | null;
      first_foundry_round: number | null;
      total_harvesters_built: number;
      total_gunners_built: number;
      total_conveyors_built: number;
      total_roads_built: number;
      total_barriers_built: number;
      total_builders_spawned: number;
      peak_builder_count: number;
      builder_spawn_rate: number;
      total_self_destructs: number;
      core_hits: number;
      core_damage_dealt: number;
      turret_shots_fired: number;
      turret_damage_dealt: number;
      self_destruct_efficiency: number;
      avg_builder_distance_from_core: number[];
      builder_positions_heatmap: number[][];
      harvesters_with_connected_chain: number;
      harvesters_without_chain: number;
      turrets_that_fired: number;
      turrets_that_never_fired: number;
    }
  >;
  core_a_hp_curve: number[];
  core_b_hp_curve: number[];
  first_blood_round: number | null;
  first_blood_team: string | null;
}
