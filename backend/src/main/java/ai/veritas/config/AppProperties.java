package ai.veritas.config;

import java.time.Duration;
import java.util.List;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Typed view of everything under {@code app.*} in application.yml. */
@ConfigurationProperties(prefix = "app")
public record AppProperties(Security security, Ai ai, Storage storage, Uploads uploads, RateLimit rateLimit, Demo demo) {

    public record Security(String jwtSecret, Duration accessTokenTtl, List<String> allowedOrigins) {
    }

    public record Ai(String baseUrl, String internalToken, Duration connectTimeout, Duration ingestTimeout,
            Duration questionTimeout) {
    }

    public record Storage(String dir) {
    }

    public record Uploads(int maxFileMb, int maxFilesPerRequest, int maxDocumentsPerInvestigation) {
    }

    public record RateLimit(int authPerMinute, int askPerMinute, int uploadPerMinute) {
    }

    public record Demo(boolean enabled) {
    }
}
