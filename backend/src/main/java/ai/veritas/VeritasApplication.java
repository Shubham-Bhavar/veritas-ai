package ai.veritas;

import java.util.TimeZone;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@ConfigurationPropertiesScan
@EnableAsync
@EnableScheduling
public class VeritasApplication {

    public static void main(String[] args) {
        // A server must not depend on the host's timezone (some hosts report legacy aliases such as
        // "Asia/Calcutta" that PostgreSQL rejects at connect time). All timestamps are stored as UTC.
        TimeZone.setDefault(TimeZone.getTimeZone("UTC"));
        SpringApplication.run(VeritasApplication.class, args);
    }
}
