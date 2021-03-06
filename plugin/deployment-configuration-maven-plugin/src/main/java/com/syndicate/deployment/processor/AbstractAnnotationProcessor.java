package com.syndicate.deployment.processor;

import com.syndicate.deployment.model.Pair;
import org.apache.maven.plugin.MojoExecutionException;

import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Created by Oleksandr Onsha on 2019-12-03
 */
public abstract class AbstractAnnotationProcessor<T> implements IAnnotationProcessor<T> {

	@Override
	public Map<String, T> generateMeta(String absolutePath, String[] packages,
	                                   String version, String fileName) throws MojoExecutionException {
		Set<String> uniqueLambdaNames = new HashSet<>();
		Map<String, T> configurations = new HashMap<>();
		List<Class<?>> annotatedClasses = getAnnotatedClasses(packages);
		for (Class<?> targetClass : annotatedClasses) {
			Pair<String, T> metaPair = process(targetClass, version, fileName, absolutePath);
			if (metaPair == null) {
				continue;
			}

			String lambdaName = metaPair.getKey();

			if (uniqueLambdaNames.contains(lambdaName)) {
				throw new MojoExecutionException("Find more than one resource with name : "
					+ lambdaName + "! Resource name must be unique.");
			} else {
				uniqueLambdaNames.add(lambdaName);
			}

			if (configurations.containsKey(lambdaName)) {
				throw new MojoExecutionException("Configuration " + lambdaName + " is duplicated.");
			}
			configurations.put(lambdaName, metaPair.getValue());
		}

		return configurations;
	}

	@Override
	public Map<String, Object> convertMeta(Map<String, T> metaConfiguration) {
		return metaConfiguration.entrySet().stream()
			.collect(Collectors.toMap(Map.Entry::getKey, e -> (Object) e.getValue()));
	}

	protected abstract Pair<String, T> process(Class<?> sourceClass, String version, String fileName, String path);

	protected abstract List<Class<?>> getAnnotatedClasses(String[] packages);
}
