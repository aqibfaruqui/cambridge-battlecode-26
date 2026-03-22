# Turrets

Defensive and offensive combat units — gunner, sentinel, breach, and launcher.

Every turret **except the launcher** faces in one of **8 directions**. Ammo must be fed to turrets via conveyors, from any direction except the direction the turret is facing. Diagonal turrets can be fed from all four sides.

Ammo-based turrets can hold up to one stack of one resource type and only accept incoming resources when completely empty.

> **Note:** If a tile containing both a building and a unit is hit, **both** take full damage.

---

## Gunner

Has a vision radius of √13. Can only target the **closest non-empty tile** in the direction it is facing. Using refined axionite as ammo deals double damage.

| Property | Value |
|----------|-------|
| HP | 40 |
| Base cost | 10 Ti |
| Scaling | 10% |
| Damage | 10 (20 with refined axionite) |
| Reload | 1 round |
| Ammo per shot | 2 |
| Vision r² | 13 |
| Attack r² | 13 (same as vision) |

---

## Sentinel

High range, low damage support turret. Can hit all tiles within **1 king move** (Chebyshev distance) of the straight line in its facing direction, within vision range.

Using refined axionite instead of titanium as ammo adds **+3 to the action and move cooldown** of any unit directly hit — acting as a stun.

| Property | Value |
|----------|-------|
| HP | 30 |
| Base cost | 15 Ti |
| Scaling | 10% |
| Damage | 20 |
| Reload | 4 rounds |
| Ammo per shot | 10 |
| Vision r² | 32 |
| Attack r² | 32 (same as vision) |

> **Tip:** Sentinels with refined axionite ammo are extremely powerful — a +3 cooldown stun can completely shut down enemy builder bots.

---

## Breach

Very high damage with **splash**. Attacks in a **180° cone** in the facing direction.

| Property | Value |
|----------|-------|
| HP | 60 |
| Base cost | 30 Ti, 10 Ax |
| Scaling | 10% |
| Damage | 40 direct + 20 splash (8 surrounding tiles) |
| Reload | 1 round |
| Ammo per shot | 5 (refined axionite only) |
| Vision r² | 10 |
| Attack r² | 5 |

> **Warning:** Breach turrets have **friendly fire** on the splash damage (8 surrounding tiles). They do not damage themselves.

---

## Launcher

Picks up and **throws adjacent builder bots** to a target tile within range. The target tile must be bot-passable. Unlike other turrets, launchers have **no facing direction** and do not use ammo.

| Property | Value |
|----------|-------|
| HP | 30 |
| Base cost | 20 Ti |
| Scaling | 10% |
| Reload | 1 round |
| Vision r² | 26 |
| Attack r² | 26 (same as vision) |
```python
# Build a launcher (no direction needed)
c.build_launcher(pos)

# Launch a builder bot to a distant position
if c.can_launch(bot_pos, target_pos):
    c.launch(bot_pos, target_pos)
```
