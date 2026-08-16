{
  description = "meetup_ical_export dev shell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            python312
            uv
            ruff
            just
            pre-commit
            gitleaks
          ];

          shellHook = ''
            [ -d .git ] && [ ! -f .git/hooks/commit-msg ] && pre-commit install --install-hooks --hook-type pre-commit --hook-type commit-msg --hook-type post-commit >/dev/null 2>&1 || true
          '';
        };
      });
}
