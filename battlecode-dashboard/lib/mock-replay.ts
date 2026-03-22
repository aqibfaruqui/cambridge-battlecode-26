import type {
  GameEvent,
  ParsedEntity,
  ParsedReplay,
  RoundSnapshot,
  TeamId,
  TileType,
} from "@/types/game";
import { CORE_FOOTPRINT, CORE_MAX_HP } from "@/lib/game-constants";

let nextId = 1;
function id() {
  return nextId++;
}

function coreEntity(team: TeamId, x: number, y: number): ParsedEntity {
  return {
    id: id(),
    type: "core",
    position: [x, y],
    hp: CORE_MAX_HP,
    team,
    footprint_w: CORE_FOOTPRINT,
    footprint_h: CORE_FOOTPRINT,
  };
}

export function generateMockReplay(roundCount = 480): ParsedReplay {
  nextId = 1;
  const width = 30;
  const height = 30;
  const tiles: TileType[][] = Array.from({ length: height }, (_, y) =>
    Array.from({ length: width }, (_, x) => {
      if (x === 0 || y === 0 || x === width - 1 || y === height - 1)
        return "wall";
      if (x === 5 && y === 10) return "ore_titanium";
      if (x === 24 && y === 19) return "ore_titanium";
      if (x === 10 && y === 5) return "ore_axionite";
      if (x === 19 && y === 24) return "ore_axionite";
      return "empty";
    }),
  );

  const rounds: RoundSnapshot[] = [];
  let tiA = 1000;
  let tiB = 1000;
  let axA = 0;
  let axB = 0;
  let scaleA = 100;
  let scaleB = 100;

  const entitiesA: ParsedEntity[] = [coreEntity("a", 3, 3)];
  const entitiesB: ParsedEntity[] = [coreEntity("b", 24, 24)];

  const allEvents: GameEvent[] = [];

  for (let r = 1; r <= roundCount; r++) {
    const events: GameEvent[] = [];

    tiA += Math.floor(Math.random() * 12);
    tiB += Math.floor(Math.random() * 10);
    axA += r % 40 === 0 ? 5 : 0;
    axB += r % 35 === 0 ? 4 : 0;
    tiA -= Math.min(15, Math.floor(r / 30));
    tiB -= Math.min(12, Math.floor(r / 35));

    if (r % 50 === 0) {
      scaleA = Math.min(450, scaleA + 8);
      scaleB = Math.min(420, scaleB + 7);
    }

    if (r === 12) {
      const h: ParsedEntity = {
        id: id(),
        type: "harvester",
        position: [5, 10],
        hp: 30,
        team: "a",
        direction: "east",
      };
      entitiesA.push(h);
      events.push({
        type: "build",
        round: r,
        team: "a",
        building_type: "harvester",
        position: [5, 10],
      });
      tiA -= 80;
    }
    if (r === 28) {
      const h: ParsedEntity = {
        id: id(),
        type: "harvester",
        position: [24, 19],
        hp: 30,
        team: "b",
        direction: "west",
      };
      entitiesB.push(h);
      events.push({
        type: "build",
        round: r,
        team: "b",
        building_type: "harvester",
        position: [24, 19],
      });
      tiB -= 80;
    }

    if (r % 8 === 0 && r < 400) {
      const bx = 4 + ((r / 8) % 5);
      const by = 4 + ((r / 8) % 4);
      const bot: ParsedEntity = {
        id: id(),
        type: "builder_bot",
        position: [bx, by],
        hp: 30,
        team: "a",
        direction: "east",
      };
      entitiesA.push(bot);
      events.push({
        type: "spawn",
        round: r,
        team: "a",
        entity_id: bot.id,
        position: [bx, by],
      });
    }

    if (r % 9 === 0 && r < 380) {
      const bx = 22 + ((r / 9) % 4);
      const by = 22 + ((r / 9) % 3);
      const bot: ParsedEntity = {
        id: id(),
        type: "builder_bot",
        position: [bx, by],
        hp: 30,
        team: "b",
        direction: "west",
      };
      entitiesB.push(bot);
      events.push({
        type: "spawn",
        round: r,
        team: "b",
        entity_id: bot.id,
        position: [bx, by],
      });
    }

    if (r === 120) {
      const g: ParsedEntity = {
        id: id(),
        type: "gunner",
        position: [8, 8],
        hp: 40,
        team: "a",
        direction: "southeast",
        ammo: 2,
      };
      entitiesA.push(g);
      events.push({
        type: "build",
        round: r,
        team: "a",
        building_type: "gunner",
        position: [8, 8],
      });
      tiA -= 10;
    }

    if (r === 200 && entitiesB.some((e) => e.type === "gunner") === false) {
      const g: ParsedEntity = {
        id: id(),
        type: "gunner",
        position: [22, 22],
        hp: 40,
        team: "b",
        direction: "northwest",
        ammo: 0,
      };
      entitiesB.push(g);
      events.push({
        type: "build",
        round: r,
        team: "b",
        building_type: "gunner",
        position: [22, 22],
      });
      tiB -= 10;
    }

    if (r === 310) {
      events.push({
        type: "fire",
        round: r,
        team: "a",
        entity_id: entitiesA.find((e) => e.type === "gunner")?.id,
        position: [8, 8],
        target: [22, 22],
        damage: 10,
      });
    }

    if (r === 340) {
      events.push({
        type: "self_destruct",
        round: r,
        team: "a",
        position: [25, 25],
        target: [25, 25],
        damage: 20,
      });
    }

    if (r === 360) {
      events.push({
        type: "damage",
        round: r,
        team: "b",
        target: [3, 3],
        damage: 40,
      });
      const core = entitiesA.find((e) => e.type === "core");
      if (core) core.hp = Math.max(0, core.hp - 40);
    }

    for (const ev of events) allEvents.push(ev);

    rounds.push({
      round_number: r,
      team_a: {
        titanium: Math.max(0, tiA),
        axionite: Math.max(0, axA),
        scale_percent: scaleA,
        entities: entitiesA.map((e) => ({ ...e })),
      },
      team_b: {
        titanium: Math.max(0, tiB),
        axionite: Math.max(0, axB),
        scale_percent: scaleB,
        entities: entitiesB.map((e) => ({ ...e })),
      },
      events,
    });
  }

  const last = rounds[rounds.length - 1];
  const coreAHp = last.team_a.entities.find((e) => e.type === "core")?.hp ?? 0;
  const coreBHp = last.team_b.entities.find((e) => e.type === "core")?.hp ?? 0;
  let winner: TeamId | null;
  let win_reason: string;
  if (coreAHp <= 0 && coreBHp <= 0) {
    winner = null;
    win_reason = "Both cores destroyed (mock)";
  } else if (coreAHp <= 0) {
    winner = "b";
    win_reason = "Team A core destroyed";
  } else if (coreBHp <= 0) {
    winner = "a";
    win_reason = "Team B core destroyed";
  } else {
    winner = coreBHp < coreAHp ? "a" : "b";
    win_reason =
      winner === "a"
        ? "Mock tiebreak: Team A ahead on core HP"
        : "Mock tiebreak: Team B ahead on core HP";
  }

  const replay: ParsedReplay = {
    map: { width, height, tiles },
    rounds,
    winner,
    win_reason,
    raw: null,
  };

  replay.raw = JSON.parse(JSON.stringify(replay));
  return replay;
}
