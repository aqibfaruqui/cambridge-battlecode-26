/** Protobuf JSON schema extracted from the Cambridge Battlecode visualiser bundle. */
export const REPLAY26_PROTO_JSON = {
  nested: {
    battlecode: {
      nested: {
        Replay: {
          fields: {
            map: { type: "Map", id: 1 },
            turns: { rule: "repeated", type: "Turn", id: 3 },
            winner: { type: "Team", id: 4, options: { proto3_optional: true } },
          },
        },
        Map: {
          fields: {
            width: { type: "int32", id: 1 },
            height: { type: "int32", id: 2 },
            rows: { rule: "repeated", type: "TileRow", id: 3 },
            cores: { rule: "repeated", type: "CorePosition", id: 4 },
          },
        },
        TileRow: {
          fields: {
            tiles: { rule: "repeated", type: "Environment", id: 1 },
          },
        },
        Players: {
          fields: {
            a: { type: "Player", id: 1 },
            b: { type: "Player", id: 2 },
          },
        },
        Player: {
          fields: {
            titanium: { type: "int32", id: 1 },
            axionite: { type: "int32", id: 2 },
            resourcesCollected: { type: "int32", id: 3 },
            titaniumCollected: { type: "int32", id: 4 },
            axioniteCollected: { type: "int32", id: 5 },
          },
        },
        Turn: {
          fields: {
            updates: { rule: "repeated", type: "Update", id: 1 },
          },
        },
        Update: {
          oneofs: {
            kind: {
              oneof: [
                "placeEntity",
                "moveBuilderBot",
                "removeEntity",
                "distributeResources",
                "updateHp",
                "updatePlayers",
                "setActionCooldown",
                "setMoveCooldown",
                "botOutput",
                "indicatorLine",
                "indicatorDot",
                "fireTurret",
              ],
            },
          },
          fields: {
            placeEntity: { type: "PlaceEntity", id: 1 },
            moveBuilderBot: { type: "MoveBuilderBot", id: 2 },
            removeEntity: { type: "RemoveEntity", id: 3 },
            distributeResources: { type: "DistributeResources", id: 4 },
            updateHp: { type: "UpdateHp", id: 5 },
            updatePlayers: { type: "UpdatePlayers", id: 6 },
            setActionCooldown: { type: "SetActionCooldown", id: 7 },
            setMoveCooldown: { type: "SetMoveCooldown", id: 8 },
            botOutput: { type: "BotOutput", id: 9 },
            indicatorLine: { type: "IndicatorLine", id: 10 },
            indicatorDot: { type: "IndicatorDot", id: 11 },
            fireTurret: { type: "FireTurret", id: 12 },
          },
        },
        PlaceEntity: {
          fields: { entity: { type: "Entity", id: 1 } },
        },
        MoveBuilderBot: {
          fields: {
            id: { type: "int32", id: 1 },
            to: { type: "Pos", id: 2 },
          },
        },
        RemoveEntity: {
          fields: { id: { type: "int32", id: 1 } },
        },
        DistributeResources: {
          fields: {
            moves: { rule: "repeated", type: "ResourceMove", id: 1 },
          },
        },
        ResourceMove: {
          fields: {
            from: { type: "Pos", id: 1 },
            to: { type: "Pos", id: 2 },
          },
        },
        UpdateHp: {
          fields: {
            id: { type: "int32", id: 1 },
            delta: { type: "int32", id: 2 },
          },
        },
        UpdatePlayers: {
          fields: { players: { type: "Players", id: 1 } },
        },
        SetActionCooldown: {
          fields: {
            id: { type: "int32", id: 1 },
            value: { type: "int32", id: 2 },
          },
        },
        SetMoveCooldown: {
          fields: {
            id: { type: "int32", id: 1 },
            value: { type: "int32", id: 2 },
          },
        },
        BotOutput: {
          fields: {
            id: { type: "int32", id: 1 },
            stdout: { type: "string", id: 2 },
            execTimeUs: { type: "uint32", id: 3 },
            tled: { type: "bool", id: 4 },
          },
        },
        IndicatorLine: {
          fields: {
            id: { type: "int32", id: 1 },
            posA: { type: "Pos", id: 2 },
            posB: { type: "Pos", id: 3 },
            r: { type: "int32", id: 4 },
            g: { type: "int32", id: 5 },
            b: { type: "int32", id: 6 },
          },
        },
        IndicatorDot: {
          fields: {
            id: { type: "int32", id: 1 },
            pos: { type: "Pos", id: 2 },
            r: { type: "int32", id: 3 },
            g: { type: "int32", id: 4 },
            b: { type: "int32", id: 5 },
          },
        },
        FireTurret: {
          fields: {
            from: { type: "Pos", id: 1 },
            to: { type: "Pos", id: 2 },
          },
        },
        Pos: {
          fields: {
            x: { type: "int32", id: 1 },
            y: { type: "int32", id: 2 },
          },
        },
        CorePosition: {
          fields: {
            id: { type: "int32", id: 1 },
            team: { type: "Team", id: 2 },
            position: { type: "Pos", id: 3 },
          },
        },
        Entity: {
          oneofs: {
            kind: {
              oneof: [
                "builderBot",
                "conveyor",
                "splitter",
                "armouredConveyor",
                "bridge",
                "harvester",
                "foundry",
                "road",
                "barrier",
                "marker",
                "core",
                "gunner",
                "sentinel",
                "breach",
                "launcher",
              ],
            },
          },
          fields: {
            id: { type: "int32", id: 1 },
            team: { type: "Team", id: 2 },
            position: { type: "Pos", id: 3 },
            hp: { type: "int32", id: 4 },
            maxHp: { type: "int32", id: 5 },
            builderBot: { type: "BuilderBot", id: 10 },
            conveyor: { type: "Conveyor", id: 11 },
            splitter: { type: "Splitter", id: 12 },
            armouredConveyor: { type: "ArmouredConveyor", id: 13 },
            bridge: { type: "Bridge", id: 14 },
            harvester: { type: "Harvester", id: 15 },
            foundry: { type: "Foundry", id: 16 },
            road: { type: "Road", id: 17 },
            barrier: { type: "Barrier", id: 18 },
            marker: { type: "Marker", id: 19 },
            core: { type: "Core", id: 20 },
            gunner: { type: "Gunner", id: 21 },
            sentinel: { type: "Sentinel", id: 22 },
            breach: { type: "Breach", id: 23 },
            launcher: { type: "Launcher", id: 24 },
          },
        },
        BuilderBot: {
          fields: {
            actionCooldown: { type: "int32", id: 1 },
            moveCooldown: { type: "int32", id: 2 },
          },
        },
        Conveyor: {
          fields: {
            direction: { type: "Direction", id: 1 },
            stored: { type: "ResourceType", id: 2 },
          },
        },
        Splitter: {
          fields: {
            direction: { type: "Direction", id: 1 },
            stored: { type: "ResourceType", id: 2 },
          },
        },
        ArmouredConveyor: {
          fields: {
            direction: { type: "Direction", id: 1 },
            stored: { type: "ResourceType", id: 2 },
          },
        },
        Bridge: {
          fields: {
            target: { type: "Pos", id: 1 },
            stored: { type: "ResourceType", id: 2 },
          },
        },
        Harvester: {
          fields: {
            cooldown: { type: "int32", id: 1 },
            resourceType: { type: "ResourceType", id: 2 },
          },
        },
        Foundry: {
          fields: { stored: { type: "ResourceType", id: 2 } },
        },
        Road: { fields: {} },
        Barrier: { fields: {} },
        Marker: {
          fields: { value: { type: "uint32", id: 1 } },
        },
        Core: {
          fields: { actionCooldown: { type: "int32", id: 1 } },
        },
        Gunner: {
          fields: {
            direction: { type: "Direction", id: 1 },
            ammoType: { type: "ResourceType", id: 2 },
            ammoAmount: { type: "int32", id: 3 },
          },
        },
        Sentinel: {
          fields: {
            direction: { type: "Direction", id: 1 },
            ammoType: { type: "ResourceType", id: 2 },
            ammoAmount: { type: "int32", id: 3 },
          },
        },
        Breach: {
          fields: {
            direction: { type: "Direction", id: 1 },
            ammoType: { type: "ResourceType", id: 2 },
            ammoAmount: { type: "int32", id: 3 },
          },
        },
        Launcher: {
          fields: {
            direction: { type: "Direction", id: 1 },
            ammoType: { type: "ResourceType", id: 2 },
            ammoAmount: { type: "int32", id: 3 },
          },
        },
        Team: { values: { TEAM_A: 0, TEAM_B: 1 } },
        Direction: {
          values: {
            DIR_CENTRE: 0,
            DIR_NORTH: 1,
            DIR_NORTHEAST: 2,
            DIR_EAST: 3,
            DIR_SOUTHEAST: 4,
            DIR_SOUTH: 5,
            DIR_SOUTHWEST: 6,
            DIR_WEST: 7,
            DIR_NORTHWEST: 8,
          },
        },
        ResourceType: {
          values: {
            RESOURCE_NONE: 0,
            RESOURCE_TITANIUM: 1,
            RESOURCE_RAW_AXIONITE: 2,
            RESOURCE_REFINED_AXIONITE: 3,
          },
        },
        Environment: {
          values: {
            ENV_EMPTY: 0,
            ENV_WALL: 1,
            ENV_ORE_TITANIUM: 2,
            ENV_ORE_AXIONITE: 3,
          },
        },
      },
    },
  },
} as const;
