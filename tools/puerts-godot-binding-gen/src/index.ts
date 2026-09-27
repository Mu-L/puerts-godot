// SPDX-FileCopyrightText: Copyright (c) 2026 puerts-godot contributors
// SPDX-License-Identifier: BSD-3-Clause

import { parseArgs } from "./cli.js";
import { generateBindings } from "./orchestrator.js";

function main(): void {
	const args = parseArgs(process.argv.slice(2));
	generateBindings(args);
}

main();
