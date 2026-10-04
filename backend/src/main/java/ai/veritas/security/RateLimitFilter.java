package ai.veritas.security;

import java.io.IOException;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import ai.veritas.config.AppProperties;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

/**
 * Fixed-window, per-client-IP limiter for the expensive or abuse-prone endpoints: sign-in
 * (credential stuffing), questions (CPU and LLM cost) and uploads (OCR cost).
 * In-memory, so each instance limits independently.
 */
@Component
public class RateLimitFilter extends OncePerRequestFilter {

    static final int MAX_TRACKED = 100_000;

    enum Bucket { AUTH, ASK, UPLOAD }

    private record Window(long minute, AtomicInteger count) {
    }

    private final Map<String, Window> windows = new ConcurrentHashMap<>();
    private final AppProperties.RateLimit limits;

    public RateLimitFilter(AppProperties properties) {
        this.limits = properties.rateLimit();
    }

    static Bucket bucketFor(String method, String path) {
        if (!"POST".equals(method)) {
            return null;
        }
        if (path.startsWith("/api/auth/")) {
            return Bucket.AUTH;
        }
        if (path.endsWith("/questions") || path.endsWith("/compare")) {
            return Bucket.ASK;
        }
        if (path.endsWith("/documents") || path.endsWith("/demo")) {
            return Bucket.UPLOAD;
        }
        return null;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return bucketFor(request.getMethod(), request.getRequestURI()) == null;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        Bucket bucket = bucketFor(request.getMethod(), request.getRequestURI());
        int limit = switch (bucket) {
            case AUTH -> limits.authPerMinute();
            case ASK -> limits.askPerMinute();
            case UPLOAD -> limits.uploadPerMinute();
        };
        if (!tryAcquire(bucket + ":" + request.getRemoteAddr(), limit)) {
            response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
            response.setHeader("Retry-After", "60");
            response.setContentType(MediaType.APPLICATION_PROBLEM_JSON_VALUE);
            response.getWriter().write("{\"status\":429,\"title\":\"Too Many Requests\",\"code\":\"RATE_LIMITED\","
                    + "\"detail\":\"Too many requests. Wait a minute and try again.\"}");
            return;
        }
        chain.doFilter(request, response);
    }

    boolean tryAcquire(String key, int limit) {
        long minute = System.currentTimeMillis() / 60_000;
        if (windows.size() >= MAX_TRACKED) {
            evictOldWindows();
        }
        Window w = windows.compute(key, (k, existing) ->
                existing == null || existing.minute() != minute ? new Window(minute, new AtomicInteger()) : existing);
        return w.count().incrementAndGet() <= limit;
    }

    @Scheduled(fixedDelay = 120_000)
    void evictOldWindows() {
        long current = System.currentTimeMillis() / 60_000;
        windows.entrySet().removeIf(e -> e.getValue().minute() < current);
    }
}
