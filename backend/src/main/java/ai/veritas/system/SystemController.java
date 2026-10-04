package ai.veritas.system;

import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import ai.veritas.ai.AiClient;
import ai.veritas.config.AppProperties;

/** Public status: which engines are live. Shown in the UI so nobody mistakes a fallback for the real thing. */
@RestController
@RequestMapping("/api/system")
public class SystemController {

    private final AiClient ai;
    private final AppProperties props;
    private volatile Map<String, Object> cached;
    private volatile long cachedAt;

    public SystemController(AiClient ai, AppProperties props) {
        this.ai = ai;
        this.props = props;
    }

    @GetMapping("/status")
    public Map<String, Object> status() {
        if (cached != null && System.currentTimeMillis() - cachedAt < 5_000) {
            return cached;
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("backend", "ok");
        out.put("demo", props.demo().enabled());
        out.put("maxFileMb", props.uploads().maxFileMb());
        try {
            out.put("ai", ai.health());
        } catch (RuntimeException e) {
            out.put("ai", Map.of("status", "unavailable"));
        }
        cached = out;
        cachedAt = System.currentTimeMillis();
        return out;
    }
}
