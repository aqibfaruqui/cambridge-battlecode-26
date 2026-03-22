# Battlecode Dashboard

Localhost analysis tool for [Cambridge Battlecode](https://battlecode.cam/) match replays. Upload `.replay26` files, browse platform matches, and get AI-powered strategic analysis via Claude.

## Setup

```bash
npm install
cp .env.example .env.local
```

Edit `.env.local` and add your Anthropic API key:

```
ANTHROPIC_API_KEY=sk-ant-api03-...
```

## Run

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Usage

### Local replays

Upload a `.replay26` file (from `cambc run`) or paste replay JSON on the home page. You'll be taken to the match dashboard with map visualization, economy charts, unit tracking, combat logs, and more.

### Browse platform matches

Click "Browse platform matches" on the home page. Search by team name to find matches, click any match to see per-game details, then click "Analyze" to load a game's replay directly into the dashboard.

Requires `cambc login` — the dashboard reads your auth token from `~/.cambc/credentials.json`.

### AI analysis

On the match dashboard, go to the "AI" tab and click "Analyze match" to stream a strategic analysis from Claude covering build orders, resource management, combat efficiency, and recommendations.

## Features

- Map visualization with official game sprites, zoom (scroll), and pan (shift+drag)
- Economy charts (titanium, axionite, scale %) with milestone annotations
- Unit composition tracking per team
- Combat log with damage-to-core charts and self-destruct efficiency
- Timeline tab: core HP over time, builder distance from core, build timeline
- Strategy comparison sidebar
- Platform match browser with team search
- Claude-powered match analysis (streamed via SSE)
