/* Physical LED strips only; J16/J17 jumper routes are intentionally omitted.
 * Coordinates follow the dashboard floorplan. The fifth cinema uses one stem
 * from the existing corridor strip, as marked in the supplied wiring plan.
 */
window.FireGuardLedPlan = [
  [[45, 140], [115, 140]],       // North exit
  [[115, 140], [115, 567]],     // West corridor
  [[45, 567], [535, 567]],      // West / east exits
  [[165, 567], [165, 645]],     // 4DX
  [[165.47, 567], [165.47, 510]], // Toilet 1 shares the 4DX junction
  [[265.344, 567], [265.344, 510]], // Toilet 2 display alignment
  [[307, 567], [307, 645]],     // Cinema 2
  [[448, 567], [448, 820]],     // South exit
  [[375, 567], [375, 267]],     // Central corridor
  [[375, 410], [435, 410]],     // Ticket office
  [[375, 362], [317, 362]],     // Cinema 4
  [[375, 315], [477, 315]],     // Popcorn approach
  [[477, 315], [477, 282]],     // Popcorn doorway
  [[385, 267], [385, 235]],     // Shop doorway
  [[115, 267], [385, 267]],     // Existing cross-corridor strip
  [[240, 267], [240, 185]],     // Single cinema 5 entrance; no upper detour
];
