import numpy as np
from typing import Iterator, List, Union, Dict

class PIDController:
    """
    @class PIDController
    @brief Thruster mixer that maps control inputs to M1..M8 (and S1..S3), with flexible matrix shapes.
    @details
      - Supports horizontal mapping as 4x3 over [X,Y,Yaw] or 4x4 over [X,Y,Z,Yaw].
      - Supports vertical   mapping as 4x1 over [Z]      or 4x3/4x4 (e.g., [X,Y,Z] or [X,Y,Z,Yaw]).
      - Outputs are normalized to [-clip, +clip] (default clip=1.0).
      - Exposes list-like access: list(self) -> [M1..M8].
    """

    def __init__(
        self,
        horizontal_mapping: np.ndarray | None = None,
        vertical_mapping:   np.ndarray | None = None,
        clip: float = 1.0
    ) -> None:
        """
        @brief Initialize controller with default (or provided) mixing matrices.
        @param horizontal_mapping  4x3 ([X,Y,Yaw]) or 4x4 ([X,Y,Z,Yaw]) for M1..M4. Defaults provided.
        @param vertical_mapping    4x1 ([Z]) or 4x3/4x4 for M5..M8. Defaults provided.
        @param clip                Absolute clamp for outputs; 1.0 keeps values in [-1,1].
        """
        # --- Defaults match your architecture: horizontals use [X,Y,Yaw], verticals use [Z] only ---

        # Rows = M1..M4, Cols = [X, Y, Yaw]
        default_h = np.array([
            [ 1.0,  1.0, -1.0],   # M1 = +X -Y (+Yaw term here if you add it)
            [ 1.0, -1.0,  1.0],   # M2 = +X +Y
            [-1.0, -1.0,  1.0],   # M3 = -X +Y
            [ 1.0, -1.0, -1.0],   # M4 = +X +Y
        ], dtype=float)

        # Rows = M5..M8, Col = [Z]
        default_v = np.array([
            [ 1.0],                # M5
            [ 1.0],                # M6
            [-1.0],                # M7
            [-1.0],                # M8
        ], dtype=float)

        self.horizontal_mapping: np.ndarray = (
            default_h if horizontal_mapping is None else np.array(horizontal_mapping, dtype=float)
        )
        self.vertical_mapping: np.ndarray = (
            default_v if vertical_mapping   is None else np.array(vertical_mapping,   dtype=float)
        )

        # Outputs (normalized)
        self.horizontal_motors: np.ndarray = np.zeros(4, dtype=float)  # M1..M4
        self.vertical_motors:   np.ndarray = np.zeros(4, dtype=float)  # M5..M8
        self.servos:            np.ndarray = np.zeros(3, dtype=float)  # S1..S3 (convenience)

        self.clip: float = float(clip)

    def set_mappings(self, horizontal_mapping: np.ndarray, vertical_mapping: np.ndarray) -> None:
        """
        @brief Replace mixing matrices at runtime.
        @param horizontal_mapping  4x3 or 4x4 matrix for horizontals (rows=M1..M4).
        @param vertical_mapping    4x1, 4x3, or 4x4 matrix for verticals (rows=M5..M8).
        """
        self.horizontal_mapping = np.array(horizontal_mapping, dtype=float)
        self.vertical_mapping   = np.array(vertical_mapping,   dtype=float)

    def _apply_mapping(self, mapping: np.ndarray, x: float, y: float, z: float, yaw: float, which: str) -> np.ndarray:
        """
        @brief Multiply with the correct input vector based on matrix width.
        @param mapping  A (4xn) matrix where n is 1, 3, or 4.
        @param which    "H" for horizontal or "V" for vertical (for error messages).
        @return (4,) output vector.
        """
        rows, cols = mapping.shape
        if rows != 4:
            raise ValueError(f"{which}-mapping must have 4 rows (got {rows}).")

        # Choose the appropriate input vector for the mapping's width.
        if cols == 1:
            vec = np.array([z], dtype=float)                 # [Z]
        elif cols == 3:
            if which == "H":
                vec = np.array([x, y, yaw], dtype=float)     # [X, Y, Yaw]
            else:
                vec = np.array([x, y, z], dtype=float)       # [X, Y, Z] if someone provides 4x3 vertical
        elif cols == 4:
            vec = np.array([x, y, z, yaw], dtype=float)      # [X, Y, Z, Yaw]
        else:
            raise ValueError(f"{which}-mapping must have 1, 3, or 4 columns (got {cols}).")

        return mapping @ vec  # shape (4,)

    def update_motors(self, x: float, y: float, z: float, yaw: float) -> None:
        """
        @brief Compute M1..M8 (and S1..S3) from inputs in normalized space.
        @param x   Surge (forward/back)
        @param y   Sway  (left/right)
        @param z   Heave (up/down)
        @param yaw Yaw   (rotation)
        @details
          - Uses horizontal_mapping and vertical_mapping with flexible shapes.
          - Clamps outputs to [-clip, +clip].
          - Servos are mirrored from [x,y,z] by default; customize as needed.
        """
        h = self._apply_mapping(self.horizontal_mapping, x, y, z, yaw, which="H")
        v = self._apply_mapping(self.vertical_mapping,   x, y, z, yaw, which="V")

        # Clamp to [-clip, +clip]
        if self.clip > 0:
            np.clip(h, -self.clip, self.clip, out=h)
            np.clip(v, -self.clip, self.clip, out=v)

        self.horizontal_motors = h
        self.vertical_motors   = v
        self.servos            = np.array([x, y, z], dtype=float)

    def as_list(self) -> Dict[str, List[float]]:
        """
        @brief Get motors/servos as Python lists.
        @return dict with keys: "horizontal", "vertical", "servos".
        """
        return {
            "horizontal": self.horizontal_motors.tolist(),
            "vertical":   self.vertical_motors.tolist(),
            "servos":     self.servos.tolist(),
        }

    def as_list_flat(self) -> List[float]:
        """
        @brief Get motors M1..M8 as a single list.
        @return [M1, M2, M3, M4, M5, M6, M7, M8]
        """
        return [*self.horizontal_motors.tolist(), *self.vertical_motors.tolist()]

    # --- List-like interface over M1..M8 ---

    def __iter__(self) -> Iterator[float]:
        """
        @brief Iterate motors in M1..M8 order.
        """
        yield from self.horizontal_motors.tolist()
        yield from self.vertical_motors.tolist()

    def __len__(self) -> int:
        """
        @brief Number of motors in the flattened view (8).
        """
        return 8

    def __getitem__(self, key: Union[int, str]) -> float:
        """
        @brief Index motors either by 0..7 or by "M1".."M8".
        @param key Index or motor name.
        @return Motor value as float.
        """
        flat = self.as_list_flat()
        if isinstance(key, int):
            return flat[key]
        if isinstance(key, str) and key.upper().startswith("M"):
            idx = int(key[1:]) - 1
            return flat[idx]
        raise KeyError(f"Invalid PID motor key: {key}")
