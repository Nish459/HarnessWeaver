/** The core's own providers: what the built-in plugin contributes (DESIGNS No. 13). */

import { memoryContext, passthroughContext } from "./context.js";
import { BUILTIN_GUARDS } from "./guards/providers.js";
import type { ProviderDef } from "./plugins/provider.js";
import { celLitePolicy } from "./policy.js";
import { lexicalStage, rulesStage } from "./routing.js";

export const BUILTIN_PROVIDERS: readonly ProviderDef[] = [...BUILTIN_GUARDS, celLitePolicy, rulesStage, lexicalStage, memoryContext, passthroughContext];
