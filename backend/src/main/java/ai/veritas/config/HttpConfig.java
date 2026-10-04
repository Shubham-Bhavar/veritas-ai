package ai.veritas.config;

import java.time.Duration;
import java.util.concurrent.Executor;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.web.client.RestClient;

@Configuration
public class HttpConfig {

    /** For ingestion: OCR on scanned pages can take tens of seconds. */
    @Bean
    public RestClient aiIngestClient(RestClient.Builder builder, AppProperties props) {
        return client(builder, props, props.ai().ingestTimeout());
    }

    /** For questions, conflicts, compare and page renders. */
    @Bean
    public RestClient aiQueryClient(RestClient.Builder builder, AppProperties props) {
        return client(builder, props, props.ai().questionTimeout());
    }

    private static RestClient client(RestClient.Builder builder, AppProperties props, Duration read) {
        SimpleClientHttpRequestFactory f = new SimpleClientHttpRequestFactory();
        f.setConnectTimeout(props.ai().connectTimeout());
        f.setReadTimeout(read);
        return builder.clone()
                .baseUrl(props.ai().baseUrl())
                .requestFactory(f)
                .defaultHeader("X-Internal-Token", props.ai().internalToken() == null ? "" : props.ai().internalToken())
                .build();
    }

    /**
     * Ingestion runs in the background, two documents at a time: the AI service is CPU-bound
     * (OCR, embeddings) and queuing beats overloading it.
     */
    @Bean(name = "ingestExecutor")
    public Executor ingestExecutor() {
        ThreadPoolTaskExecutor ex = new ThreadPoolTaskExecutor();
        ex.setCorePoolSize(2);
        ex.setMaxPoolSize(2);
        ex.setQueueCapacity(500);
        ex.setThreadNamePrefix("ingest-");
        ex.initialize();
        return ex;
    }
}
